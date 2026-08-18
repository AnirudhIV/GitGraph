const CAT_VARS = ["--cat-1", "--cat-2", "--cat-3", "--cat-4", "--cat-5", "--cat-6", "--cat-7", "--cat-8"];

export function moduleColorVar(name: string): string {
  let hash = 0;
  for (let i = 0; i < name.length; i++) {
    hash = (hash * 31 + name.charCodeAt(i)) >>> 0;
  }
  return `var(${CAT_VARS[hash % CAT_VARS.length]})`;
}

export function ModuleChip({ name }: { name: string }) {
  if (!name) return null;
  return (
    <span className="badge">
      <span className="badge-dot" style={{ background: moduleColorVar(name) }} />
      {name}
    </span>
  );
}
