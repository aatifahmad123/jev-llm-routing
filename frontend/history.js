const CLIENT_ID_KEY = "rag-chat-client-id";
window.chatClientId = localStorage.getItem(CLIENT_ID_KEY) || crypto.randomUUID();
localStorage.setItem(CLIENT_ID_KEY, window.chatClientId);

async function loadHistory() {
  const response = await fetch(
    `/conversations?client_id=${encodeURIComponent(window.chatClientId)}`
  );
  if (!response.ok) throw new Error("Unable to load chat history");
  return response.json();
}

function renderHistory(conversations) {
  const historyList = document.querySelector(".history-list");
  if (!historyList) return;

  historyList.replaceChildren();
  conversations.forEach((conversation) => {
    const item = document.createElement("button");
    item.type = "button";
    item.className = "history-item";
    item.textContent = conversation.title;
    item.title = conversation.title;
    item.addEventListener("click", () => {
      window.location.href = `/?conversation=${encodeURIComponent(conversation.id)}`;
    });
    historyList.appendChild(item);
  });
}

loadHistory()
  .then(renderHistory)
  .catch((error) => console.error(error));
