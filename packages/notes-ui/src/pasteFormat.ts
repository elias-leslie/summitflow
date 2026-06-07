const MIN_TABLE_COLUMNS = 2;

export function formatNotePaste(text: string, html?: string): string {
    const normalizedText = normalizeNewlines(text);
    const htmlTableMarkdown = html ? htmlTablesToMarkdown(html) : null;
    if (htmlTableMarkdown) return htmlTableMarkdown;
    return convertPlainTextTables(normalizedText);
}

function normalizeNewlines(value: string): string {
    return value.replace(/\r\n?/g, '\n');
}

function htmlTablesToMarkdown(html: string): string | null {
    if (typeof document === 'undefined' || !html.toLowerCase().includes('<table')) return null;

    const container = document.createElement('div');
    container.innerHTML = html;
    const tables = Array.from(container.querySelectorAll('table'));
    if (tables.length === 0) return null;

    const markdownTables = tables
        .map(table => {
            const rows = Array.from(table.querySelectorAll('tr'))
                .map(row => Array.from(row.querySelectorAll('th,td')).map(cell => cleanCell(cell.textContent ?? '')))
                .filter(row => row.some(Boolean));
            return rowsToMarkdown(rows);
        })
        .filter((table): table is string => Boolean(table));

    return markdownTables.length > 0 ? markdownTables.join('\n\n') : null;
}

function convertPlainTextTables(text: string): string {
    const markdownNormalized = normalizeMarkdownTableBlocks(text);
    const tabNormalized = convertDelimitedBlocks(markdownNormalized, splitTabRow);
    return convertDelimitedBlocks(tabNormalized, splitSpacedRow);
}

function normalizeMarkdownTableBlocks(text: string): string {
    const lines = text.split('\n');
    const output: string[] = [];
    let index = 0;
    let inFence = false;

    while (index < lines.length) {
        const line = lines[index];
        if (line.trim().startsWith('```')) inFence = !inFence;
        if (inFence || !line.includes('|')) {
            output.push(line);
            index += 1;
            continue;
        }

        const block: string[] = [];
        let cursor = index;
        while (cursor < lines.length && lines[cursor].includes('|') && lines[cursor].trim()) {
            block.push(lines[cursor]);
            cursor += 1;
        }

        const rows = parseMarkdownTableBlock(block);
        const markdown = rows ? rowsToMarkdown(rows) : null;
        if (markdown) {
            output.push(markdown);
            index = cursor;
        } else {
            output.push(line);
            index += 1;
        }
    }

    return output.join('\n');
}

function convertDelimitedBlocks(text: string, splitter: (line: string) => string[] | null): string {
    const lines = text.split('\n');
    const output: string[] = [];
    let index = 0;
    let inFence = false;

    while (index < lines.length) {
        const line = lines[index];
        if (line.trim().startsWith('```')) {
            inFence = !inFence;
            output.push(line);
            index += 1;
            continue;
        }

        if (inFence) {
            output.push(line);
            index += 1;
            continue;
        }

        const firstRow = splitter(line);
        if (!firstRow) {
            output.push(line);
            index += 1;
            continue;
        }

        const rows: string[][] = [firstRow];
        let cursor = index + 1;
        while (cursor < lines.length) {
            const nextRow = splitter(lines[cursor]);
            if (!nextRow) break;
            rows.push(nextRow);
            cursor += 1;
        }

        const markdown = rowsToMarkdown(rows);
        if (rows.length >= 2 && markdown) {
            output.push(markdown);
            index = cursor;
        } else {
            output.push(line);
            index += 1;
        }
    }

    return output.join('\n');
}

function parseMarkdownTableBlock(lines: string[]): string[][] | null {
    if (lines.length < 2) return null;
    const rows = lines
        .filter(line => !isMarkdownSeparator(line))
        .map(splitMarkdownRow)
        .filter(row => row.length >= MIN_TABLE_COLUMNS);
    return rows.length >= 2 ? rows : null;
}

function splitMarkdownRow(line: string): string[] {
    return line
        .trim()
        .replace(/^\|/, '')
        .replace(/\|$/, '')
        .split('|')
        .map(cleanCell);
}

function splitTabRow(line: string): string[] | null {
    if (!line.includes('\t')) return null;
    const cells = line.split('\t').map(cleanCell);
    return cells.length >= MIN_TABLE_COLUMNS && cells.some(Boolean) ? cells : null;
}

function splitSpacedRow(line: string): string[] | null {
    const trimmed = line.trim();
    if (!trimmed || isDividerLine(trimmed) || /^[-*+]\s+/.test(trimmed) || /^\d+[.)]\s+/.test(trimmed)) return null;
    const cells = trimmed.split(/\s{3,}/).map(cleanCell);
    return cells.length >= 3 && cells.some(Boolean) ? cells : null;
}

function rowsToMarkdown(rows: string[][]): string | null {
    if (rows.length < 2) return null;
    const width = Math.max(...rows.map(row => row.length));
    if (width < MIN_TABLE_COLUMNS) return null;

    const normalizedRows = rows.map(row => normalizeRow(row, width));
    const header = normalizedRows[0].map((cell, index) => cell || `Column ${index + 1}`);
    const body = normalizedRows.slice(1);

    return [
        markdownRow(header),
        markdownRow(header.map(() => '---')),
        ...body.map(markdownRow),
    ].join('\n');
}

function normalizeRow(row: string[], width: number): string[] {
    return Array.from({ length: width }, (_, index) => row[index] ?? '');
}

function markdownRow(row: string[]): string {
    return `| ${row.map(escapeMarkdownCell).join(' | ')} |`;
}

function cleanCell(value: string): string {
    return value.replace(/\s+/g, ' ').trim();
}

function escapeMarkdownCell(value: string): string {
    return value.replace(/\|/g, '\\|');
}

function isMarkdownSeparator(line: string): boolean {
    return /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(line);
}

function isDividerLine(line: string): boolean {
    return /^[\s|_\-=—–]+$/.test(line) && line.length >= 3;
}
