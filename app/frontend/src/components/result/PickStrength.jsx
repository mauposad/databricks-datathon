import Icon from '../Icon.jsx'
import { Button, Popover } from '../ui/index.js'

// "How solid is this pick?" (#1 only): the double-checks behind the one-line verdict.
function CheckRow({ c }) {
  const result = c.still_first === true ? <span className="still"><Icon name="check" /> Still #1</span>
    : c.still_first === false ? <span className="moves"><Icon name="arrowRight" /> {c.winner} would be #1</span>
    : <span className="muted">No facility passes this check</span>
  return <li><span className="check-label">{c.label}</span>{result}</li>
}

export function DoubleChecks({ rec }) {
  const data = rec.double_checks.filter((c) => c.kind === 'data')
  const situation = rec.double_checks.filter((c) => c.kind === 'situation')
  return (
    <div className="pick-checks">
      <p className="small muted">
        We re-ran the ranking {data.length} more times, each time doubting one part of the data. If #1 stays on top
        every time, it is a solid pick. If not, the facility that takes its place is the one to call second.
      </p>
      <ul>{data.map((c) => <CheckRow key={c.label} c={c} />)}</ul>
      {situation.length > 0 && (
        <>
          <p className="pick-sub">If your situation is different</p>
          <ul>{situation.map((c) => <CheckRow key={c.label} c={c} />)}</ul>
        </>
      )}
    </div>
  )
}

export default function PickStrength({ rec }) {
  const solid = rec.pick_strength === 'Solid'
  const nData = rec.double_checks.filter((c) => c.kind === 'data').length
  return (
    <li className={`pick ${solid ? 'solid' : 'shaky'}`}>
      <Icon name={solid ? 'shield' : 'warning'} />
      <span>
        {rec.pick_strength_note}{' '}
        {nData > 0 && (
          <Popover label="Double-checks" className="popover-wide"
                   trigger={<Button variant="ghost" size="sm" className="inline-link">See the {nData} double-checks</Button>}>
            <DoubleChecks rec={rec} />
          </Popover>
        )}
      </span>
    </li>
  )
}
