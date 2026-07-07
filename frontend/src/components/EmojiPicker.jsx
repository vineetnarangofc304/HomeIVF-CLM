import React from "react";

const EMOJIS = ["😀","😃","😄","😁","😊","😍","😘","😎","🤩","🥳","🙂","🤗","🤔","👍","👎","🙏","👏","💪","🔥","✨","🎉","❤️","💛","💚","💙","💜","✅","❌","⭐","📞","📅","💬","📎","🩺","👶","🤰","🎯","⏰","😢","😅"];

export default function EmojiPicker({ onPick, onClose }) {
  return (
    <div data-testid="emoji-picker" className="absolute bottom-14 left-2 z-30 w-64 rounded-2xl border border-slate-200 bg-white p-2 shadow-xl">
      <div className="grid grid-cols-8 gap-1">
        {EMOJIS.map((e) => (
          <button key={e} type="button" data-testid={`emoji-${e}`}
            onClick={() => { onPick(e); onClose && onClose(); }}
            className="rounded-lg p-1 text-lg transition-colors hover:bg-slate-100">{e}</button>
        ))}
      </div>
    </div>
  );
}
