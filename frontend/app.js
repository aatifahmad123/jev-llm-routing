const chatEl = document.getElementById("chat");
const queryEl = document.getElementById("query");
const sendBtn = document.getElementById("send");
const clearBtn = document.getElementById("clear-chat");
const newChatBtn = document.getElementById("new-chat");

const API_BASE = "";
let messages = [];
let conversationId = new URLSearchParams(window.location.search).get("conversation");

function renderMessage(role, text, isError = false, meta = null) {
  const div = document.createElement("div");
  div.className = `msg ${role}${isError ? " error" : ""}`;

  const labelRow = document.createElement("div");
  labelRow.className = "label-row";

  const label = document.createElement("span");
  label.className = "label";
  label.textContent = role === "user" ? "You" : "Assistant";
  labelRow.appendChild(label);

  if (role === "bot" && meta) {
    const tag = document.createElement("span");
    tag.className = `tag ${meta.route === "large" ? "tag-large" : "tag-small"}`;
    tag.textContent = meta.route === "large"
      ? "groq - openai/gpt-oss-120b"
      : "ollama - llama3.2:3b";
    labelRow.appendChild(tag);
  }

  div.appendChild(labelRow);

  const body = document.createElement("div");
  body.textContent = text;
  div.appendChild(body);

  chatEl.appendChild(div);
  chatEl.scrollTop = chatEl.scrollHeight;
  return div;
}

function renderMessages() {
  chatEl.replaceChildren();
  messages.forEach(({ role, text, is_error: isError, meta }) => {
    renderMessage(role, text, isError, meta);
  });
}

async function requestConversation() {
  const response = await fetch(
    `/conversations?client_id=${encodeURIComponent(window.chatClientId)}`
  );
  if (!response.ok) throw new Error("Unable to load chat history");
  const conversations = await response.json();

  if (conversationId && conversations.some(({ id }) => id === conversationId)) {
    return conversationId;
  }

  if (conversations.length) return conversations[0].id;

  return null;
}

async function loadConversation(id) {
  if (!id) {
    conversationId = null;
    window.history.replaceState({}, "", "/");
    messages = [];
    renderMessages();
    return;
  }

  const response = await fetch(
    `/conversations/${encodeURIComponent(id)}/messages?client_id=${encodeURIComponent(window.chatClientId)}`
  );
  if (!response.ok) throw new Error("Unable to load conversation");
  conversationId = id;
  window.history.replaceState({}, "", `/?conversation=${encodeURIComponent(id)}`);
  messages = await response.json();
  renderMessages();
}

async function refreshHistory() {
  const response = await fetch(
    `/conversations?client_id=${encodeURIComponent(window.chatClientId)}`
  );
  if (!response.ok) throw new Error("Unable to refresh chat history");
  const conversations = await response.json();
  const historyList = document.querySelector(".history-list");
  historyList.replaceChildren();
  conversations.forEach((conversation) => {
    const item = document.createElement("button");
    item.type = "button";
    item.className = "history-item";
    item.textContent = conversation.title;
    item.title = conversation.title;
    item.addEventListener("click", () => loadConversation(conversation.id));
    historyList.appendChild(item);
  });
}

async function createNewChat() {
  await loadConversation(null);
  await refreshHistory();
}

async function clearChat() {
  if (!conversationId || !messages.length || !window.confirm("Clear this chat history?")) {
    return;
  }

  const response = await fetch(
    `/conversations/${encodeURIComponent(conversationId)}/messages?client_id=${encodeURIComponent(window.chatClientId)}`,
    { method: "DELETE" }
  );
  if (!response.ok) {
    console.error("Unable to clear chat history");
    return;
  }
  messages = [];
  renderMessages();
  await refreshHistory();
}

async function send() {
  const query = queryEl.value.trim();
  if (!query) return;

  sendBtn.disabled = true;
  queryEl.value = "";
  renderMessage("user", query);
  const thinking = renderMessage("bot", "thinking…");
  thinking.classList.add("thinking");

  try {
    const res = await fetch(`${API_BASE}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        query,
        client_id: window.chatClientId,
        conversation_id: conversationId,
      }),
    });
    const data = await res.json();

    thinking.remove();
    if (!res.ok) {
      renderMessage("bot", data.detail || "Request failed", true);
      return;
    }

    conversationId = data.conversation_id;
    renderMessage("bot", data.answer, false, {
      route: data.route,
      model: data.model,
    });
    messages = await fetch(
      `/conversations/${encodeURIComponent(conversationId)}/messages?client_id=${encodeURIComponent(window.chatClientId)}`
    ).then((response) => response.json());
    await refreshHistory();
  } catch (error) {
    thinking.remove();
    renderMessage("bot", `Network error: ${error.message}`, true);
  } finally {
    sendBtn.disabled = false;
    queryEl.focus();
  }
}

async function initialize() {
  try {
    await loadConversation(await requestConversation());
    await refreshHistory();
  } catch (error) {
    renderMessage("bot", error.message, true);
  }
}

newChatBtn.addEventListener("click", () => {
  createNewChat().catch((error) => console.error(error));
});
clearBtn.addEventListener("click", () => {
  clearChat().catch((error) => console.error(error));
});
sendBtn.addEventListener("click", send);
queryEl.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    send();
  }
});

initialize();
