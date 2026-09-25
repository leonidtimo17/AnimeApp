import json

import pytest

from anime_app.application.backup import BackupService
from anime_app.core.errors import ValidationError
from anime_app.infrastructure.database.repositories import (AnimeRepository, HttpCacheRepository, LibraryRepository,
                                                           ProgressRepository, SettingsRepository)


def release(i=1, **kw):
    return {"id": i, "name": {"main": f"Тайтл {i}", "english": f"Title {i}"}, "shikimori": {"id": 500 + i},
            "genres": [{"name": "Экшен"}], **kw}


def test_schema_has_indexes(db):
    names = {r["name"] for r in db.query("SELECT name FROM sqlite_master WHERE type='index'")}
    assert {"idx_progress_anime_updated", "idx_library_status", "idx_http_cache_ts"} <= names


def test_anime_save_keeps_full_data_and_batches(db):
    repo = AnimeRepository(db)
    repo.save(release(1), "poster", "2020", full=True)
    repo.save(release(1, year=2021), "poster2", "2021", full=False)   # неполная карточка не затирает данные
    assert repo.release(1)["genres"] == [{"name": "Экшен"}]
    copy = repo.release(1)
    copy["name"]["main"] = "изменено"
    assert repo.release(1)["name"]["main"] == "Тайтл 1"                # наружу — копия
    repo.save(release(2), None, "", full=True)
    assert set(repo.releases([1, 2, 3])) == {1, 2}
    assert repo.shiki_ids() == {1: 501, 2: 502}


def test_library_update_and_cleanup(db):
    repo = LibraryRepository(db)
    AnimeRepository(db).save(release(1), None, "", full=True)
    repo.update(1, status="planned")
    repo.update(1, favorite=1)
    assert repo.entry(1)["status"] == "planned" and repo.entry(1)["favorite"] == 1
    assert repo.counts()["planned"] == 1 and repo.counts()["favorite"] == 1
    assert [r["id"] for r in repo.list("planned")] == [1]
    repo.update(1, status=None, favorite=0)
    assert db.one("SELECT COUNT(*) FROM library")[0] == 0              # пустая запись удалена
    assert repo.entry(1)["status"] is None


def test_progress_watched_and_history(db):
    AnimeRepository(db).save(release(1), None, "", full=True)
    progress = ProgressRepository(db)
    assert progress.save(1, "1", 1, 10 * 60_000, 24 * 60_000) == (False, False)
    assert progress.save(1, "1", 1, 23 * 60_000, 24 * 60_000) == (True, True)
    assert progress.save(1, "1", 1, 5 * 60_000, 24 * 60_000) == (True, False)    # отметка не снимается
    progress.save(1, "2", 2, 60_000, 24 * 60_000)
    assert progress.last(1)["episode_id"] == "2"
    assert [r["episode_id"] for r in progress.continue_watching()] == ["2"]
    assert len(progress.history()) == 2
    progress.clear_history()
    assert progress.for_anime(1)["1"]["watched"] == 1 and "2" not in progress.for_anime(1)
    assert progress.stats()["episodes"] == 1


def test_continue_watching_hides_completed(db):
    AnimeRepository(db).save(release(1), None, "", full=True)
    ProgressRepository(db).save(1, "1", 1, 60_000, 24 * 60_000)
    LibraryRepository(db).update(1, status="completed")
    assert ProgressRepository(db).continue_watching() == []


def test_settings_cache_returns_copies(db):
    s = SettingsRepository(db)
    assert s.get("x", 5) == 5
    s.set("filters", {"genres": [1]})
    got = s.get("filters")
    got["genres"].append(2)
    assert s.get("filters") == {"genres": [1]}
    assert SettingsRepository(db).get("filters") == {"genres": [1]}    # в базе


def test_http_cache_ttl(db):
    c = HttpCacheRepository(db)
    c.put("k", "body")
    assert c.get("k", 60) == "body" and c.get("k", None) == "body"
    db.execute("UPDATE http_cache SET ts = ts - 100")
    assert c.get("k", 60) is None and c.get("k", None) == "body"
    assert c.stats() == (1, 4)
    c.clear()
    assert c.get("k", None) is None


def test_transaction_rolls_back(db):
    repo = LibraryRepository(db)
    with pytest.raises(RuntimeError):
        with db.transaction():
            repo.update(1, status="planned")
            raise RuntimeError("сбой посреди записи")
    assert repo.entry(1)["status"] is None


def _backup(db):
    return BackupService(db, AnimeRepository(db), LibraryRepository(db), ProgressRepository(db),
                         HttpCacheRepository(db))


def test_backup_roundtrip_keeps_full_release(db, tmp_path):
    AnimeRepository(db).save(release(1), None, "", full=True)
    LibraryRepository(db).update(1, status="watching", score=9)
    ProgressRepository(db).save(1, "1", 1, 60_000, 24 * 60_000)
    path = str(tmp_path / "backup.json")
    service = _backup(db)
    service.export_json(path)
    db.execute("DELETE FROM library")
    assert service.import_json(path) == 3
    assert LibraryRepository(db).entry(1)["score"] == 9
    assert AnimeRepository(db).release(1)["genres"]                     # полная карточка не пропала


def test_backup_rejects_bad_files_and_sql_in_column_names(db, tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("не json", encoding="utf-8")
    with pytest.raises(ValidationError):
        _backup(db).import_json(str(bad))
    evil = tmp_path / "evil.json"
    evil.write_text(json.dumps({"library": [{"anime_id": 1, "status": "planned",
                                             "status) VALUES (1,'x'); DROP TABLE progress; --": 1}]}),
                    encoding="utf-8")
    assert _backup(db).import_json(str(evil)) == 1
    assert db.one("SELECT COUNT(*) FROM progress") is not None          # таблица на месте
    assert LibraryRepository(db).entry(1)["status"] == "planned"
