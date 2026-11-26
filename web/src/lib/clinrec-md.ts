/** В клинических рекомендациях ** и *** — пометы препарата и изделия, а не выделение. */
export function prepareClinrecMarkdown(markdown: string): string {
  return markdown
    .replace(/^[•●▪]\s*/gm, "- ")
    .replace(/\*\*\*/g, "\\*\\*\\*")
    .replace(/\*\*/g, "\\*\\*");
}
