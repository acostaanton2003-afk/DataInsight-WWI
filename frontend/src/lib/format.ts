const integer = new Intl.NumberFormat('es-ES');
export const formatCount = (value: number) => integer.format(value);
export function formatAmount(value: string): string {
  if (!/^-?\d+\.\d{2}$/.test(value)) throw new Error('Importe inválido.');
  const negative = value.startsWith('-');
  const [whole, cents] = (negative ? value.slice(1) : value).split('.');
  return `${negative ? '−' : ''}${integer.format(BigInt(whole))},${cents}`;
}
export function monthLabel(year: number | null, month: number | null) {
  if (year === null || month === null) return 'Sin fecha';
  return new Intl.DateTimeFormat('es-ES', {month:'short', year:'numeric', timeZone:'UTC'})
    .format(new Date(Date.UTC(year, month - 1, 1))).replace('.', '');
}
export const axisAmount = (value: number) => new Intl.NumberFormat('es-ES', {
  notation: 'compact', maximumFractionDigits: 1,
}).format(value);
