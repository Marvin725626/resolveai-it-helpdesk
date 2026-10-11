/** Quote CSV cells and neutralize spreadsheet formula prefixes in user text. */
export function ticketCsv(rows: string[][]): string {
  const quote = (value: string) => {
    const safe = /^[=+@\-\t\r\n]/.test(value.trimStart()) ? "'" + value : value;
    return `"${safe.replace(/"/g, '""')}"`;
  };
  return '\uFEFF' + rows.map(row => row.map(quote).join(',')).join('\r\n');
}
