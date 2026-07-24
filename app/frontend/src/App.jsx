import { useEffect, useState } from "react";

// API address comes from a build-time variable, so the same code points at a
// laptop backend or a cloud backend with no change.
const API = import.meta.env.VITE_API_URL || "";

export default function App() {
  const [ideas, setIdeas] = useState([]);
  const [text, setText] = useState("");
  const [error, setError] = useState("");

  // Which idea is being edited, and the working text for the edit box.
  const [editingId, setEditingId] = useState(null);
  const [editText, setEditText] = useState("");

  async function load() {
    try {
      const res = await fetch(`${API}/api/ideas`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setIdeas(await res.json());
      setError("");
    } catch (e) {
      setError("Could not load ideas. Is the backend running?");
    }
  }

  useEffect(() => {
    load();
  }, []);

  // CREATE
  async function submit(e) {
    e.preventDefault();
    const content = text.trim();
    if (!content) return;
    try {
      const res = await fetch(`${API}/api/ideas`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setText("");
      load();
    } catch (e) {
      setError("Could not save. Is the backend running?");
    }
  }

  function startEdit(idea) {
    setEditingId(idea.id);
    setEditText(idea.content);
  }

  function cancelEdit() {
    setEditingId(null);
    setEditText("");
  }

  // UPDATE
  async function saveEdit(id) {
    const content = editText.trim();
    if (!content) return;
    try {
      const res = await fetch(`${API}/api/ideas/${id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      cancelEdit();
      load();
    } catch (e) {
      setError("Could not update. Is the backend running?");
    }
  }

  // DELETE
  async function remove(id) {
    try {
      const res = await fetch(`${API}/api/ideas/${id}`, { method: "DELETE" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      if (editingId === id) cancelEdit();
      load();
    } catch (e) {
      setError("Could not delete. Is the backend running?");
    }
  }

  return (
    <main className="wrap">
      <div className="hero">
        <h1>🚀 Idea Board</h1>
        <p className="tagline">Fresh look — shipped via an AI-powered preview 🎉</p>
      </div>
      <form onSubmit={submit} className="row">
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Your next big idea..."
          aria-label="New idea"
        />
        <button type="submit">Add</button>
      </form>
      {error && <p className="error">{error}</p>}
      <ul>
        {ideas.map((i) => (
          <li key={i.id}>
            {editingId === i.id ? (
              <div className="row">
                <input
                  value={editText}
                  onChange={(e) => setEditText(e.target.value)}
                  aria-label="Edit idea"
                  autoFocus
                />
                <button onClick={() => saveEdit(i.id)}>Save</button>
                <button className="ghost" onClick={cancelEdit}>
                  Cancel
                </button>
              </div>
            ) : (
              <div className="item">
                <span className="content">{i.content}</span>
                <span className="actions">
                  <button className="ghost" onClick={() => startEdit(i)}>
                    Edit
                  </button>
                  <button className="danger" onClick={() => remove(i.id)}>
                    Delete
                  </button>
                </span>
              </div>
            )}
          </li>
        ))}
        {ideas.length === 0 && !error && (
          <li className="empty">No ideas yet — add one above.</li>
        )}
      </ul>
      <footer className="foot">Preview build · idea-board</footer>
    </main>
  );
}
