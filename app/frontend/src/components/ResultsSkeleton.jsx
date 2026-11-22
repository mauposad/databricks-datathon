import { Skeleton } from './ui/index.js'

// Matches the real layout: one hero card, then four compact rows.
export default function ResultsSkeleton() {
  return (
    <div className="cards" role="status" aria-label="Searching">
      <div className="card hero skeleton-card" aria-hidden>
        <div className="card-head">
          <Skeleton width={28} height={28} radius="var(--r-pill)" />
          <div className="title"><Skeleton width="70%" height={20} /><Skeleton width="45%" height={14} style={{ marginTop: 8 }} /></div>
        </div>
        <div className="stats">
          {[0, 1, 2].map((i) => <div key={i} className="stat"><Skeleton width={48} height={12} /><Skeleton width={i ? 64 : 96} height={i ? 24 : 32} style={{ marginTop: 4 }} /></div>)}
        </div>
        <Skeleton height={72} radius="var(--r-md)" style={{ marginTop: 16 }} />
        <div className="actions"><Skeleton width={200} height={48} radius="var(--r-md)" /><Skeleton width={120} height={40} radius="var(--r-md)" /></div>
      </div>
      <div className="rows" aria-hidden>
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="card row"><div className="row-head">
            <Skeleton width={28} height={28} radius="var(--r-pill)" />
            <div className="row-title"><Skeleton width={`${60 - i * 6}%`} height={14} /></div>
            <Skeleton width={56} height={14} /><Skeleton width={40} height={32} radius="var(--r-md)" />
          </div></div>
        ))}
      </div>
    </div>
  )
}
