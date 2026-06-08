export default function TypingIndicator() {
  return (
    <div className="flex items-center gap-1.5 px-1 py-0.5">
      {[0, 150, 300].map((delay, i) => (
        <span
          key={i}
          className="w-2 h-2 rounded-full bg-accent animate-bounce"
          style={{ animationDelay: `${delay}ms` }}
        />
      ))}
    </div>
  )
}
