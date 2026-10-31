(function () {
  const L = window.LMN, root = L.root;
  const ICON = { done: "✓", later: "•", nope: "✗" };
  const LABEL = { later: "Отложить", done: "Прослушано", nope: "Не понравилось" };
  let token = null, marks = {};
  try { token = localStorage.getItem("lmn_token"); } catch (e) {}
  if ("serviceWorker" in navigator) navigator.serviceWorker.register(root + "sw.js").catch(() => {});

  async function api(path, opts = {}) {
    if (!L.worker) throw new Error("no worker");
    const r = await fetch(L.worker + path, { ...opts, headers: { "Content-Type": "application/json", ...(token ? { Authorization: "Bearer " + token } : {}) } });
    if (r.status === 401) { token = null; try { localStorage.removeItem("lmn_token"); } catch (e) {} }
    return r.json();
  }

  // ---- login (Telegram Login Widget) ----
  window.lmnLogin = async (user) => {
    const d = await api("/auth/telegram", { method: "POST", body: JSON.stringify(user) });
    if (d.token) { token = d.token; try { localStorage.setItem("lmn_token", token); } catch (e) {} location.reload(); }
  };
  const slot = document.getElementById("login");
  if (L.worker && !token) {
    const s = document.createElement("script");
    s.src = "https://telegram.org/js/telegram-widget.js?22";
    s.async = true;
    s.dataset.telegramLogin = L.bot; s.dataset.size = "small"; s.dataset.onauth = "lmnLogin(user)"; s.dataset.requestAccess = "write";
    slot.appendChild(s);
  } else if (token) {
    slot.innerHTML = '<a href="#" id="logout" class="muted">выйти</a>';
    document.getElementById("logout").onclick = (ev) => { ev.preventDefault(); try { localStorage.removeItem("lmn_token"); } catch (e) {} location.reload(); };
  }

  async function loadMarks() {
    if (!token) return;
    try { marks = (await api("/api/me/marks")).marks || {}; } catch (e) { marks = {}; }
    document.querySelectorAll("li[data-id]").forEach((li) => { const m = marks[li.dataset.id]; li.querySelector(".st").textContent = m && m.status ? ICON[m.status] : ""; });
  }

  // ---- release page: my marks + public average ----
  const rel = document.querySelector(".release");
  if (rel) {
    const id = rel.dataset.id, box = rel.querySelector(".mine");
    api("/api/public").then((d) => {
      const a = d.avg && d.avg[id];
      if (a) rel.querySelector(".avg").textContent = `Средняя оценка посетителей: ${a.avg} (${a.n})`;
      const mv = (d.moods && d.moods[id]) || {};
      const ok = Object.entries(mv).filter(([, v]) => v.y > v.n).map(([m]) => m);
      const el = rel.querySelector(".moods");
      if (el && ok.length) el.innerHTML = ok.join(" / ") + ' <span class="muted">(подтверждено голосованием)</span>';
    }).catch(() => {});
    if (token) loadMarks().then(() => {
      const m = marks[id] || {};
      box.hidden = false;
      box.innerHTML = "<b>Мои отметки</b> <span class='muted'>(видны только тебе)</span><p class='btns'>" +
        Object.keys(LABEL).map((k) => `<button data-s="${k}" class="${m.status === k ? "btn on" : "btn"}">${ICON[k]} ${LABEL[k]}</button>`).join("") +
        "</p><label>Моя оценка: <select id='myscore'><option value=''>—</option>" +
        [...Array(11).keys()].map((n) => `<option ${m.score === n ? "selected" : ""}>${n}</option>`).join("") + "</select></label>";
      box.querySelectorAll("button").forEach((b) => b.onclick = async () => {
        const s = (marks[id] || {}).status === b.dataset.s ? null : b.dataset.s;
        await api("/api/mark", { method: "POST", body: JSON.stringify({ review_id: id, status: s }) });
        marks[id] = { ...(marks[id] || {}), status: s };
        box.querySelectorAll("button").forEach((x) => x.className = x.dataset.s === s ? "btn on" : "btn");
      });
      box.querySelector("#myscore").onchange = (ev) => api("/api/mark", { method: "POST", body: JSON.stringify({ review_id: id, score: ev.target.value === "" ? null : Number(ev.target.value) }) });
    });
  }

  // ---- catalog ----
  const list = document.getElementById("catalog");
  if (!list) return;
  const q = document.getElementById("q"), fs = document.getElementById("fscore"), fg = document.getElementById("fgenre"),
    fy = document.getElementById("fyear"), fh = document.getElementById("fhide"), more = document.getElementById("more");
  let all = [], shown = 50;
  const colorOf = (x) => x.ng ? "red" : x.cl ? "green" : x.s == null ? "none" : x.s >= 8 ? "green" : x.s >= 5 ? "neutral" : "red";
  const labelOf = (x) => x.ng ? "NOT GOOD" : x.cl ? "CLASSIC" : x.s == null ? "?" : x.s;
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  function render() {
    const text = q.value.trim().toLowerCase(), sc = fs.value, g = fg.value, y = fy.value, hide = fh.checked && token;
    const rows = all.filter((x) =>
      (!text || (x.a + " " + x.t).toLowerCase().includes(text)) &&
      (!sc || (sc === "red" ? colorOf(x) === "red" : (x.s != null && x.s >= Number(sc)) || (x.cl && Number(sc) <= 10))) &&
      (!g || x.g.includes(g)) && (!y || x.d.startsWith(y)) &&
      (!hide || !(marks[x.i] && marks[x.i].status === "done")));
    list.innerHTML = rows.slice(0, shown).map((x) =>
      `<li data-id="${esc(x.i)}"><span class="score ${colorOf(x)}">${labelOf(x)}</span> <a href="${x.p ? root + "r/" + esc(x.i) + ".html" : esc(x.u)}">${esc(x.a)} — ${esc(x.t)}</a>` +
      `<span class="muted"> ${esc([x.g[0], x.d.slice(0, 4), x.gu ? "гостевой" : ""].filter(Boolean).join(" · "))}</span><span class="st">${marks[x.i] && marks[x.i].status ? ICON[marks[x.i].status] : ""}</span></li>`).join("") || "<li>Ничего не нашлось.</li>";
    more.hidden = rows.length <= shown;
  }
  fetch(root + "catalog.json").then((r) => r.json()).then((d) => {
    all = d.filter((x) => x.a);
    const genres = {}; all.forEach((x) => x.g.forEach((g) => genres[g] = (genres[g] || 0) + 1));
    Object.entries(genres).filter(([, n]) => n >= 5).sort((a, b) => b[1] - a[1]).slice(0, 150)
      .forEach(([g]) => fg.insertAdjacentHTML("beforeend", `<option>${esc(g)}</option>`));
    [...new Set(all.map((x) => x.d.slice(0, 4)))].sort().reverse().forEach((yr) => fy.insertAdjacentHTML("beforeend", `<option>${yr}</option>`));
    render();
  });
  [q, fs, fg, fy, fh].forEach((el) => el.addEventListener("input", () => { shown = 50; render(); }));
  more.onclick = () => { shown += 100; render(); };
  loadMarks().then(render);
})();
