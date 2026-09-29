document.addEventListener("submit", (e) => {
  const msg = e.target.dataset.confirm;
  if (msg && !confirm(msg)) e.preventDefault();
});

async function checkChannel() {
  const chat = document.getElementById("chat_lookup").value.trim();
  const out = document.getElementById("chat_result");
  if (!chat) { out.textContent = "Введите @username, ссылку или id канала"; return; }
  out.textContent = "Проверяю…";
  const fd = new FormData();
  fd.append("chat", chat);
  fd.append("join_request", document.querySelector("[name=join_request]").checked ? "on" : "");
  const res = await fetch("/sponsors/api/check", { method: "POST", body: fd });
  const data = await res.json();
  if (!data.ok) { out.innerHTML = `<span class="badge err">Ошибка</span> ${data.error}`; return; }
  document.querySelector("[name=chat_id]").value = data.chat_id;
  const title = document.querySelector("[name=title]");
  if (!title.value) title.value = data.title || "";
  if (data.url) document.querySelector("[name=url]").value = data.url;
  out.innerHTML = (data.is_admin ? '<span class="badge ok">Бот — админ ✓</span> ' : '<span class="badge warn">Бот не админ</span> ') +
    `${data.title} <span class="muted mono">${data.chat_id}</span>` + (data.warning ? `<div class="hint">${data.warning}</div>` : "") +
    (data.url ? '<div class="hint">Создана персональная ссылка-приглашение — по ней считаются вступления из бота.</div>' : "");
}

function livePreview() {
  const text = document.querySelector("[name=text]");
  const pv = document.getElementById("preview");
  if (!text || !pv) return;
  const render = () => {
    const safe = text.value.replace(/<(?!\/?(b|i|u|s|a|code|pre|tg-spoiler)\b)[^>]*>/gi, "");
    let html = safe.replace(/\n/g, "<br>");
    document.querySelectorAll("[data-btn]").forEach((row) => {
      const t = row.querySelector("input[name^=btn_text], input[name=button_text]");
      if (t && t.value) html += `<span class="pbtn">${t.value.replace(/</g, "&lt;")}</span>`;
    });
    pv.innerHTML = html || '<span class="muted">Предпросмотр сообщения</span>';
  };
  document.addEventListener("input", render);
  render();
}
document.addEventListener("DOMContentLoaded", livePreview);
