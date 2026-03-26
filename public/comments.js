(function () {
  const API = location.hostname === "localhost" || location.hostname === "127.0.0.1"
    ? "http://127.0.0.1:3000/api/comments"
    : "/api/comments";

  function relativeTime(dateStr) {
    const diff = (Date.now() - new Date(dateStr + "Z").getTime()) / 1000;
    if (diff < 60) return "刚刚";
    if (diff < 3600) return Math.floor(diff / 60) + " 分钟前";
    if (diff < 86400) return Math.floor(diff / 3600) + " 小时前";
    if (diff < 2592000) return Math.floor(diff / 86400) + " 天前";
    return new Date(dateStr + "Z").toLocaleDateString("zh-CN");
  }

  function escape(str) {
    return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  function renderComment(c, isReply) {
    const time = new Date(c.created_at + "Z").toLocaleString("zh-CN");
    return `
      <div class="c-item${isReply ? " c-reply" : ""}" id="c-${c.id}">
        <div class="c-meta">
          <span class="c-name">${escape(c.name)}</span>
          <span class="c-time" title="${time}">${relativeTime(c.created_at)}</span>
          <button class="c-reply-btn" data-id="${c.id}" data-name="${escape(c.name)}">回复</button>
        </div>
        <div class="c-body">${escape(c.content)}</div>
      </div>`;
  }

  function buildTree(comments) {
    const map = {};
    const roots = [];
    comments.forEach(c => { map[c.id] = { ...c, children: [] }; });
    comments.forEach(c => {
      if (c.parent_id && map[c.parent_id]) {
        map[c.parent_id].children.push(map[c.id]);
      } else {
        roots.push(map[c.id]);
      }
    });
    return roots;
  }

  function renderTree(nodes) {
    return nodes.map(c => {
      const children = c.children.length
        ? `<div class="c-children">${renderTree(c.children)}</div>`
        : "";
      return renderComment(c, false) + children;
    }).join("");
  }

  async function loadComments(container, pageKey) {
    const list = container.querySelector(".c-list");
    list.innerHTML = "<div class='c-loading'>加载中…</div>";
    try {
      const res = await fetch(`${API}?page=${encodeURIComponent(pageKey)}`);
      const data = await res.json();
      if (data.length === 0) {
        list.innerHTML = "<div class='c-empty'>还没有评论，来说点什么吧</div>";
      } else {
        const tree = buildTree(data);
        list.innerHTML = renderTree(tree);
      }
    } catch {
      list.innerHTML = "<div class='c-empty'>评论加载失败</div>";
    }
  }

  function initForm(container, pageKey) {
    const form = container.querySelector(".c-form");
    const nameInput = container.querySelector(".c-input-name");
    const emailInput = container.querySelector(".c-input-email");
    const contentInput = container.querySelector(".c-input-content");
    const replyTip = container.querySelector(".c-reply-tip");
    const submitBtn = container.querySelector(".c-submit");
    let parentId = null;

    container.addEventListener("click", e => {
      const btn = e.target.closest(".c-reply-btn");
      if (!btn) return;
      parentId = parseInt(btn.dataset.id);
      const name = btn.dataset.name;
      replyTip.textContent = `回复 @${name}`;
      replyTip.style.display = "inline";
      contentInput.focus();
      contentInput.value = "";
    });

    replyTip.addEventListener("click", () => {
      parentId = null;
      replyTip.style.display = "none";
    });

    form.addEventListener("submit", async e => {
      e.preventDefault();
      const name = nameInput.value.trim();
      const content = contentInput.value.trim();
      if (!name || !content) return;

      submitBtn.disabled = true;
      submitBtn.textContent = "提交中…";

      try {
        const res = await fetch(API, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            page_key: pageKey,
            parent_id: parentId,
            name,
            email: emailInput.value.trim() || null,
            content,
          }),
        });

        if (res.status === 429) {
          alert("提交太频繁，请稍后再试");
          return;
        }
        if (!res.ok) {
          alert("提交失败，请重试");
          return;
        }

        contentInput.value = "";
        parentId = null;
        replyTip.style.display = "none";
        await loadComments(container, pageKey);
      } catch {
        alert("网络错误，请重试");
      } finally {
        submitBtn.disabled = false;
        submitBtn.textContent = "提交";
      }
    });
  }

  function init() {
    const container = document.getElementById("comments");
    if (!container) return;
    const pageKey = container.dataset.page || location.pathname;

    container.innerHTML = `
      <div class="c-list"></div>
      <form class="c-form">
        <div class="c-form-row">
          <input class="c-input c-input-name" type="text" placeholder="昵称（必填）" required maxlength="50" />
          <input class="c-input c-input-email" type="email" placeholder="邮箱（选填，不公开）" maxlength="100" />
        </div>
        <span class="c-reply-tip" style="display:none;cursor:pointer;" title="点击取消回复"></span>
        <textarea class="c-input c-input-content" placeholder="说点什么…" required maxlength="2000"></textarea>
        <div class="c-form-actions">
          <button class="c-submit" type="submit">提交</button>
        </div>
      </form>`;

    loadComments(container, pageKey);
    initForm(container, pageKey);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
