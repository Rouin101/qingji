/** Decorative artwork is deliberately separate from evidence and progress states. */
export function FieldworkArt({kind = 'map', className = ''}) {
  return <img className={`fieldwork-art ${className}`} src={`/assets/fieldwork-${kind}.png`} alt="" aria-hidden="true" draggable="false" width="180" height="180"/>;
}
