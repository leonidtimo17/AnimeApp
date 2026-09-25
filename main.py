import sys


def main():
    # Отдельный процесс окна веб-плеера (озвучки через Kodik).
    if len(sys.argv) > 2 and sys.argv[1] == "--webplayer":
        from anime_app.presentation.player.webplayer import run
        run(sys.argv[2])
        return

    from anime_app.app import run
    sys.exit(run())


if __name__ == "__main__":
    main()
