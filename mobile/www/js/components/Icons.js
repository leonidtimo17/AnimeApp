// Иконки Font Awesome (шрифт в www/fonts): I.play → код символа, fa("play") → разметка иконки.

export const I = {
  play: "&#xf04b;", pause: "&#xf04c;", back: "&#xf060;", prev: "&#xf048;", next: "&#xf051;", fwd: "&#xf04e;",
  rewind: "&#xf2ea;", forward: "&#xf2f9;", list: "&#xf0ca;", expand: "&#xf065;", compress: "&#xf066;",
  heart: "&#xf004;", bookmark: "&#xf02e;", star: "&#xf005;", check: "&#xf00c;", circleCheck: "&#xf058;",
  plus: "&#x2b;", mic: "&#xf130;", layers: "&#xf5fd;", gear: "&#xf013;", calendar: "&#xf073;", magic: "&#xe2ca;",
  refresh: "&#xf2f9;", trash: "&#xf2ed;", filter: "&#xf0b0;", history: "&#xf1da;", moon: "&#xf186;", comments: "&#xf086;",
  link: "&#xf0c1;", zoom: "&#xf00e;", wifi: "&#xf1eb;", gauge: "&#xf625;",
};

/** cls: "fa" — сплошная, "far" — контурная. */
export const fa = (k, cls = "fa") => `<i class="${cls}">${I[k]}</i>`;
