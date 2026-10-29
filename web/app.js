/* Оренда без ріелторів — логіка сторінки. Без сторонніх бібліотек. */
(function () {
  "use strict";
  const $ = (s, el = document) => el.querySelector(s);
  const PAGE = 20;
  const BOOL_KEYS = ["nf", "nl", "pets", "kids", "furn", "tech", "photo", "sure"];
  const NUM_KEYS = ["pmin", "pmax", "amin", "amax"];
  const LABELS = {
    nf: "Не перший поверх", nl: "Не останній поверх", pets: "З тваринами", kids: "З дітьми",
    furn: "З меблями", tech: "З технікою", photo: "З фото", sure: "Лише від власника",
  };

  let meta = null;
  const cache = {};
  let state = readUrl();
  let shownCount = PAGE;

  // ------------------------------------------------------------ стан у посиланні
  function readUrl() {
    const p = new URLSearchParams(location.search);
    const s = { city: p.get("city") || "", district: p.get("district") || "", sort: p.get("sort") || "new",
      rooms: (p.get("rooms") || "").split(",").filter(Boolean), age: p.get("age") || "" };
    NUM_KEYS.forEach(k => { s[k] = p.get(k) || ""; });
    BOOL_KEYS.forEach(k => { s[k] = p.get(k) === "1"; });
    return s;
  }
  function writeUrl() {
    const p = new URLSearchParams();
    if (state.city) p.set("city", state.city);
    if (state.district) p.set("district", state.district);
    NUM_KEYS.forEach(k => { if (state[k]) p.set(k, state[k]); });
    if (state.rooms.length) p.set("rooms", state.rooms.join(","));
    BOOL_KEYS.forEach(k => { if (state[k]) p.set(k, "1"); });
    if (state.age) p.set("age", state.age);
    if (state.sort && state.sort !== "new") p.set("sort", state.sort);
    const q = p.toString();
    history.replaceState(null, "", location.pathname + (q ? "?" + q : ""));
  }

  // ------------------------------------------------------------ дані
  async function getJson(url) {
    const r = await fetch(url, { cache: "no-cache" });
    if (!r.ok) throw new Error(r.status + " " + url);
    return r.json();
  }
  async function loadCity(slug) {
    if (!cache[slug]) cache[slug] = await getJson("data/" + encodeURIComponent(slug) + ".json");
    return cache[slug];
  }

  // ------------------------------------------------------------ фільтрація
  function num(v) { const n = parseFloat(String(v).replace(/\s/g, "").replace(",", ".")); return isNaN(n) ? null : n; }
  function filtered(rows) {
    const pmin = num(state.pmin), pmax = num(state.pmax), amin = num(state.amin), amax = num(state.amax);
    let since = null;
    if (state.age === "1") { const d = new Date(); d.setHours(0, 0, 0, 0); since = d.getTime(); }
    else if (state.age) since = Date.now() - Number(state.age) * 864e5;
    const rooms = state.rooms.map(Number);
    const out = rows.filter(r => {
      if (state.district && r.district !== state.district) return false;
      if (pmin !== null && r.price < pmin) return false;
      if (pmax !== null && r.price > pmax) return false;
      if (amin !== null && !(r.area >= amin)) return false;
      if (amax !== null && !(r.area <= amax)) return false;
      if (rooms.length) {
        if (!r.rooms) return false;
        const ok = rooms.some(n => n === 4 ? r.rooms >= 4 : r.rooms === n);
        if (!ok) return false;
      }
      if (state.nf && !(r.floor > 1)) return false;
      if (state.nl && !(r.floor && r.floors && r.floor < r.floors)) return false;
      if (state.pets && r.pets !== true) return false;
      if (state.kids && r.kids !== true) return false;
      if (state.furn && r.furniture !== true) return false;
      if (state.tech && r.appliances !== true) return false;
      if (state.photo && !(r.photos && r.photos.length)) return false;
      if (state.sure && r.trust !== "owner") return false;
      if (since && !(Date.parse(r.published) >= since)) return false;
      return true;
    });
    if (state.sort === "cheap") out.sort((a, b) => a.price - b.price);
    else if (state.sort === "expensive") out.sort((a, b) => b.price - a.price);
    else out.sort((a, b) => (b.published || "").localeCompare(a.published || ""));
    return out;
  }

  // ------------------------------------------------------------ формати
  const esc = s => String(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const money = n => Math.round(n).toLocaleString("uk-UA").replace(/,/g, " ");
  const MONTHS = ["січня", "лютого", "березня", "квітня", "травня", "червня", "липня", "серпня", "вересня", "жовтня", "листопада", "грудня"];
  function when(iso) {
    if (!iso) return "";
    const d = new Date(iso), now = new Date();
    const t = d.toLocaleTimeString("uk-UA", { hour: "2-digit", minute: "2-digit" });
    const day = x => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
    const diff = Math.round((day(now) - day(d)) / 864e5);
    if (diff === 0) return "сьогодні о " + t;
    if (diff === 1) return "вчора о " + t;
    return d.getDate() + " " + MONTHS[d.getMonth()] + (d.getFullYear() !== now.getFullYear() ? " " + d.getFullYear() : "");
  }
  function roomsWord(n) { return n === 1 ? "кімната" : (n >= 2 && n <= 4 ? "кімнати" : "кімнат"); }
  function fmtArea(a) { return (Math.round(a * 10) / 10).toString().replace(".", ","); }

  // ------------------------------------------------------------ картка
  function card(r, cityName) {
    const el = $("#cardTpl").content.firstElementChild.cloneNode(true);
    // фото
    const track = $(".gallery__track", el), count = $(".gallery__count", el);
    const photos = r.photos || [];
    if (!photos.length) {
      track.innerHTML = '<div class="gallery__none">Без фото</div>';
      count.remove(); el.querySelectorAll(".gallery__nav").forEach(b => b.remove());
    } else {
      photos.forEach((src, i) => {
        const img = document.createElement("img");
        img.loading = "lazy"; img.decoding = "async"; img.referrerPolicy = "no-referrer";
        img.alt = i === 0 ? (r.title || "Фото квартири") : "";
        img.src = src;
        img.onerror = () => { img.style.visibility = "hidden"; };
        track.appendChild(img);
      });
      const upd = () => { const i = track.clientWidth ? Math.round(track.scrollLeft / track.clientWidth) : 0; count.textContent = (i + 1) + " / " + photos.length; };
      upd(); track.addEventListener("scroll", () => requestAnimationFrame(upd), { passive: true });
      if (photos.length < 2) { el.querySelectorAll(".gallery__nav").forEach(b => b.remove()); }
      else {
        $(".gallery__nav--prev", el).onclick = () => track.scrollBy({ left: -track.clientWidth, behavior: "smooth" });
        $(".gallery__nav--next", el).onclick = () => track.scrollBy({ left: track.clientWidth, behavior: "smooth" });
      }
    }
    // ціна і довіра
    $(".price", el).innerHTML = money(r.price) + " <small>грн/міс</small>" +
      (r.old_price && r.old_price !== r.price ? " <s>" + money(r.old_price) + "</s>" : "");
    const t = $(".trust", el);
    t.textContent = r.trust === "owner" ? "Від власника" : "Сумнівно";
    t.className = "trust trust--" + (r.trust === "owner" ? "owner" : "doubt");
    // факти
    const facts = [];
    if (r.rooms) facts.push(r.rooms + " " + roomsWord(r.rooms));
    if (r.area) facts.push(fmtArea(r.area) + " м²");
    if (r.floor) facts.push("поверх " + r.floor + (r.floors ? " з " + r.floors : ""));
    $(".facts", el).textContent = facts.join(" · ") || "Параметри не вказані";
    $(".place", el).textContent = cityName + (r.district ? ", " + r.district + " р-н" : "");
    $(".title", el).textContent = r.title || "";
    const text = $(".text", el), moreBtn = $(".more-text", el);
    text.textContent = r.text || "";
    if ((r.text || "").length < 220) moreBtn.remove();
    else moreBtn.onclick = () => { const o = text.classList.toggle("open"); moreBtn.textContent = o ? "Згорнути" : "Читати повністю"; };
    // ознаки
    const feat = [];
    const yesNo = (v, yes, no) => { if (v === true) feat.push(yes); else if (v === false) feat.push(no); };
    yesNo(r.furniture, "З меблями", "Без меблів");
    yesNo(r.appliances, "З технікою", "Без техніки");
    yesNo(r.pets, "Можна з тваринами", "Без тварин");
    yesNo(r.kids, "Можна з дітьми", "Без дітей");
    if (r.n_sources > 1) feat.push("Об'єднано " + r.n_sources + " оголошення");
    $(".feat", el).innerHTML = feat.map(f => "<span>" + f + "</span>").join("");
    $(".why", el).textContent = r.why ? "Чому сумнівно: " + r.why.join("; ") : "";
    $(".date", el).textContent = when(r.published);
    $(".date", el).title = "Опубліковано: " + new Date(r.published).toLocaleString("uk-UA") +
      (r.updated && r.updated !== r.published ? "\nОновлено: " + new Date(r.updated).toLocaleString("uk-UA") : "");
    // посилання
    const links = $(".links", el);
    const order = { OLX: 0, LUN: 1 };
    const counter = {};
    (r.links || []).slice().sort((a, b) => order[a.site] - order[b.site]).forEach(l => {
      counter[l.site] = (counter[l.site] || 0) + 1;
      if (counter[l.site] > 2) return;
      const a = document.createElement("a");
      a.href = l.url; a.target = "_blank"; a.rel = "noopener noreferrer";
      a.className = l.site.toLowerCase();
      a.textContent = l.site + (counter[l.site] > 1 ? " ще" : "") + " ↗";
      links.appendChild(a);
    });
    return el;
  }

  // ------------------------------------------------------------ відмалювання
  async function render(resetPaging) {
    if (resetPaging) shownCount = PAGE;
    const city = meta.cities.find(c => c.slug === state.city) || meta.cities[0];
    state.city = city.slug;
    $("#city").value = city.slug;
    $("#sort").value = state.sort;
    writeUrl();
    updateBadges(city);
    const list = $("#list");
    let rows;
    try { rows = await loadCity(city.slug); }
    catch (e) { list.innerHTML = '<div class="empty">Не вдалося завантажити оголошення. Оновіть сторінку.</div>'; return; }
    const res = filtered(rows);
    $("#summary").textContent = res.length
      ? "Знайдено " + res.length + " з " + rows.length
      : "Нічого не знайдено";
    list.innerHTML = "";
    if (!res.length) {
      list.innerHTML = '<div class="empty">За цими фільтрами оголошень немає.<br>Спробуйте прибрати частину фільтрів.</div>';
    }
    const frag = document.createDocumentFragment();
    res.slice(0, shownCount).forEach(r => frag.appendChild(card(r, city.name)));
    list.appendChild(frag);
    const more = $("#more");
    more.hidden = res.length <= shownCount;
    more.textContent = "Показати ще (" + Math.min(PAGE, res.length - shownCount) + ")";
  }

  function activeFilters() {
    const a = [];
    if (state.district) a.push(["district", state.district + " р-н"]);
    if (state.pmin || state.pmax) a.push(["price", "Ціна " + (state.pmin ? "від " + state.pmin + " " : "") + (state.pmax ? "до " + state.pmax : "")]);
    if (state.amin || state.amax) a.push(["area", "Площа " + (state.amin ? "від " + state.amin + " " : "") + (state.amax ? "до " + state.amax : "") + " м²"]);
    if (state.rooms.length) a.push(["rooms", "Кімнат: " + state.rooms.map(x => x === "4" ? "4+" : x).join(", ")]);
    BOOL_KEYS.forEach(k => { if (state[k]) a.push([k, LABELS[k]]); });
    if (state.age) a.push(["age", { "1": "Сьогодні", "3": "За 3 дні", "7": "За тиждень" }[state.age]]);
    return a;
  }
  function clearFilter(key) {
    if (key === "price") { state.pmin = state.pmax = ""; }
    else if (key === "area") { state.amin = state.amax = ""; }
    else if (key === "rooms") state.rooms = [];
    else if (BOOL_KEYS.includes(key)) state[key] = false;
    else state[key] = "";
  }
  function updateBadges() {
    const act = activeFilters();
    const b = $("#filterCount");
    b.hidden = !act.length; b.textContent = act.length;
    const chips = $("#activeChips");
    chips.innerHTML = "";
    act.forEach(([key, label]) => {
      const c = document.createElement("button");
      c.type = "button"; c.className = "chip"; c.textContent = label;
      c.setAttribute("aria-label", "Прибрати фільтр: " + label);
      c.onclick = () => { clearFilter(key); render(true); };
      chips.appendChild(c);
    });
  }

  // ------------------------------------------------------------ панель фільтрів
  const form = $("#filters"), sheet = $("#sheet");
  function openSheet() {
    const city = meta.cities.find(c => c.slug === state.city) || meta.cities[0];
    const ds = $("#district");
    ds.innerHTML = '<option value="">Усі райони</option>' +
      city.districts.map(d => "<option>" + esc(d) + "</option>").join("");
    ds.value = state.district;
    NUM_KEYS.forEach(k => { form.elements[k].value = state[k]; });
    form.querySelectorAll('input[name="rooms"]').forEach(i => { i.checked = state.rooms.includes(i.value); });
    BOOL_KEYS.forEach(k => { form.elements[k].checked = state[k]; });
    form.querySelectorAll('input[name="age"]').forEach(i => { i.checked = i.value === state.age; });
    sheet.hidden = false;
    document.body.style.overflow = "hidden";
  }
  function closeSheet() { sheet.hidden = true; document.body.style.overflow = ""; }
  form.addEventListener("submit", e => {
    e.preventDefault();
    state.district = form.elements.district.value;
    NUM_KEYS.forEach(k => { state[k] = form.elements[k].value.replace(/\D/g, ""); });
    state.rooms = [...form.querySelectorAll('input[name="rooms"]:checked')].map(i => i.value);
    BOOL_KEYS.forEach(k => { state[k] = form.elements[k].checked; });
    const age = form.querySelector('input[name="age"]:checked');
    state.age = age ? age.value : "";
    closeSheet(); render(true); window.scrollTo({ top: 0 });
  });
  $("#resetFilters").onclick = () => {
    ["district", "age"].forEach(k => { state[k] = ""; });
    NUM_KEYS.forEach(k => { state[k] = ""; }); state.rooms = [];
    BOOL_KEYS.forEach(k => { state[k] = false; });
    closeSheet(); render(true);
  };
  sheet.addEventListener("click", e => { if (e.target.closest("[data-close]")) closeSheet(); });
  document.addEventListener("keydown", e => { if (e.key === "Escape" && !sheet.hidden) closeSheet(); });
  $("#openFilters").onclick = openSheet;
  $("#city").onchange = e => { state.city = e.target.value; state.district = ""; render(true); window.scrollTo({ top: 0 }); };
  $("#sort").onchange = e => { state.sort = e.target.value; render(true); };
  $("#more").onclick = () => { shownCount += PAGE; render(false); };

  // ------------------------------------------------------------ поділитися
  function toast(msg) { const t = $("#toast"); t.textContent = msg; t.classList.add("show"); setTimeout(() => t.classList.remove("show"), 2200); }
  $("#shareBtn").onclick = async () => {
    const url = location.href;
    if (navigator.share) { try { await navigator.share({ title: "Добірка квартир", url }); return; } catch (e) { if (e.name === "AbortError") return; } }
    try { await navigator.clipboard.writeText(url); toast("Посилання на добірку скопійовано"); }
    catch (e) { prompt("Скопіюйте посилання:", url); }
  };

  // ------------------------------------------------------------ підвал
  function footer() {
    const f = $("#foot");
    const upd = meta.updated ? new Date(meta.updated).toLocaleString("uk-UA", { day: "numeric", month: "long", hour: "2-digit", minute: "2-digit" }) : "—";
    const bad = (meta.status || []).filter(s => !s.ok);
    const st = meta.stats || {};
    let html = "Оновлено: " + upd + ". Дані оновлюються автоматично кожні ~3 години.<br>";
    if (st.hidden_words || st.hidden_agents || st.merged_duplicates) {
      html += "Приховано через слова ріелторів: " + (st.hidden_words || 0) + ", ймовірних посередників: " + (st.hidden_agents || 0) +
        ", об'єднано дублікатів: " + (st.merged_duplicates || 0) + ".<br>";
    }
    if (bad.length) {
      html += '<details><summary class="bad">Проблеми з джерелами (' + bad.length + ")</summary>" +
        bad.map(s => esc(s.source + " · " + s.city + ": " + s.note)).join("<br>") + "</details>";
    }
    html += "Перед оплатою завжди перевіряйте власника й документи на квартиру.";
    f.innerHTML = html;
  }

  // ------------------------------------------------------------ старт
  (async function init() {
    try { meta = await getJson("data/meta.json"); }
    catch (e) { $("#summary").textContent = "Дані ще не зібрані. Зачекайте на перше оновлення."; return; }
    const sel = $("#city");
    sel.innerHTML = meta.cities.map(c => '<option value="' + esc(c.slug) + '">' + esc(c.name) + " (" + c.count + ")</option>").join("");
    footer();
    render(true);
  })();
})();
