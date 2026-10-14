const chatEl = document.getElementById("chat");
const queryEl = document.getElementById("query");
const sendBtn = document.getElementById("send");

const API_BASE = "";

function appendMessage(role, text, isError = false, meta = null) {
  const div = document.createElement("div");
  div.className = `msg ${role}${isError ? " error" : ""}`;

  // Label row (You / Assistant + tag)
  const labelRow = document.createElement("div");
  labelRow.className = "label-row";

  const label = document.createElement("span");
  label.className = "label";
  label.textContent = role === "user" ? "You" : "Assistant";
  labelRow.appendChild(label);

  // Tag next to Assistant
  if (role === "bot" && meta) {
    const tag = document.createElement("span");
    tag.className = "tag";
    if (meta.route === "large") {
      tag.textContent = "groq - openai/gpt-oss-120b";
      tag.classList.add("tag-large");
    } else {
      tag.textContent = "ollama - llama3.2:3b";
      tag.classList.add("tag-small");
    }
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

async function send() {
  const query = queryEl.value.trim();
  if (!query) return;

  sendBtn.disabled = true;
  queryEl.value = "";
  appendMessage("user", query);

  const thinking = appendMessage("bot", "thinking…");
  thinking.classList.add("thinking");

  try {
    const res = await fetch(`${API_BASE}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query }),
    });

    const data = await res.json();

    if (!res.ok) {
      thinking.remove();
      appendMessage("bot", data.detail || "Request failed", true);
      return;
    }

    thinking.remove();
    appendMessage("bot", data.answer, false, {
      route: data.route,
      model: data.model,
    });
  } catch (err) {
    thinking.remove();
    appendMessage("bot", `Network error: ${err.message}`, true);
  } finally {
    sendBtn.disabled = false;
    queryEl.focus();
  }
}

sendBtn.addEventListener("click", send);
queryEl.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    send();
  }
});