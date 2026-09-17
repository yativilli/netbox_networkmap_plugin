(function () {
    const button = document.querySelector('[data-export-svg]');
    if (!button) return;

    const SVG_NS = 'http://www.w3.org/2000/svg';
    const WIDTH = 1200;
    const RIGHT_PAD = 16;
    const BOTTOM_PAD = 16;
    const FONT = 'system-ui, -apple-system, "Segoe UI", Roboto, sans-serif';

    const STYLE = [
        'text { font-family: ' + FONT + '; fill: #212529; }',
        '.h-section { font-size: 16px; font-weight: 700; fill: #1f2937; }',
        '.p-title { font-size: 14.5px; font-weight: 700; }',
        '.f-label { font-size: 12px; font-weight: 700; fill: #6b7280; }',
        '.f-value { font-size: 12px; }',
        '.c-title { font-size: 12.5px; font-weight: 700; }',
        '.c-label { font-size: 11.5px; font-weight: 700; fill: #6b7280; }',
        '.c-value { font-size: 11.5px; }',
        '.chip-name { font-size: 12.5px; font-weight: 700; }',
        '.chip-count { font-size: 12.5px; }',
        '.n-title { font-size: 13.5px; font-weight: 700; }',
        '.n-sub { font-size: 11px; fill: #6c757d; }',
        '.i-label { font-size: 11.5px; font-weight: 700; fill: #6b7280; }',
        '.i-value { font-size: 11.5px; }',
    ].join('\n');

    const measureCtx = document.createElement('canvas').getContext('2d');

    function textWidth(text, font) {
        measureCtx.font = font;
        return measureCtx.measureText(text).width;
    }

    function esc(value) {
        return String(value == null ? '' : value)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    // Word wrapping with hard breaks for overlong tokens (URLs, hostnames);
    // returns at most maxLines lines, the last one ellipsised on overflow.
    function wrap(text, font, maxWidth, maxLines) {
        const words = String(text == null ? '' : text).split(/\s+/).filter(Boolean);
        const lines = [];
        let current = '';
        words.forEach((word) => {
            let chunk = word;
            while (textWidth(chunk, font) > maxWidth && chunk.length > 1) {
                let head = '';
                let i = 1;
                while (i < chunk.length && textWidth(chunk.slice(0, i + 1), font) <= maxWidth) i += 1;
                head = chunk.slice(0, i);
                chunk = chunk.slice(i);
                lines.push(current ? current + ' ' + head : head);
                current = '';
            }
            const candidate = current ? current + ' ' + chunk : chunk;
            if (textWidth(candidate, font) <= maxWidth || !current) {
                current = candidate;
                return;
            }
            lines.push(current);
            current = chunk;
        });
        if (current) lines.push(current);
        if (!lines.length) lines.push('');
        if (maxLines && lines.length > maxLines) {
            const kept = lines.slice(0, maxLines);
            let last = kept[maxLines - 1];
            while (last.length > 1 && textWidth(last + '\u2026', font) > maxWidth) {
                last = last.slice(0, -1);
            }
            kept[maxLines - 1] = last.replace(/[\s.,;:)+/-]+$/, '') + '\u2026';
            return kept;
        }
        return lines;
    }

    function text(x, y, value, cls, extra) {
        return `<text x="${x}" y="${y}" class="${cls}"${extra || ''}>${esc(value)}</text>`;
    }

    function locationRgb(el) {
        // The cards expose their location color as an "r, g, b" custom
        // property; read it from the live DOM instead of guessing.
        const raw = el ? getComputedStyle(el).getPropertyValue('--location-color').trim() : '';
        return raw ? `rgb(${raw.replace(/\s+/g, '')})` : 'rgb(108, 117, 125)';
    }

    function fieldList(card) {
        return Array.from(card.querySelectorAll(':scope > .card-body > p.card-text')).map((p) => {
            const strong = p.querySelector('strong');
            const label = strong ? strong.textContent.trim() : '';
            const value = p.textContent
                .slice(strong ? strong.textContent.length : 0)
                .replace(/^[\s:]+/, '').trim();
            return { label, value };
        });
    }

    // Draws "Label: value..." and returns the height plus continuation-line
    // x offset; shared by the parent and child cards of the machine list.
    function drawFields(out, fields, x, y, maxWidth, labelCls, valueCls, rowHeight, titleFont) {
        fields.forEach((field) => {
            const labelFont = `700 ${titleFont}px ${FONT}`;
            const labelWidth = textWidth(field.label, labelFont) + 6;
            const lines = wrap(field.value, `400 ${titleFont}px ${FONT}`, maxWidth - labelWidth);
            lines.forEach((line, index) => {
                if (index === 0) {
                    out.push(`<text x="${x}" y="${y}" class="${labelCls}">${esc(field.label)}</text>`);
                    out.push(`<text x="${x + labelWidth}" y="${y}" class="${valueCls}">${esc(line)}</text>`);
                } else {
                    out.push(`<text x="${x + labelWidth}" y="${y}" class="${valueCls}">${esc(line)}</text>`);
                }
                y += rowHeight;
            });
        });
        return y;
    }

    /* ------------------------------------------------------------------
       Machine list: overview chips + one card per VLAN with its machines
       ------------------------------------------------------------------ */

    function drawMachineList(target) {
        const out = [];
        let y = 16;
        const innerW = WIDTH - RIGHT_PAD;

        const sections = target.querySelectorAll('.card-header .card-title');
        const overviewTitle = sections[0] ? sections[0].textContent.trim() : 'Overview';
        const elementsTitle = sections[1] ? sections[1].textContent.trim() : 'VLAN Elements';

        // Overview chips, one per VLAN with its machine count.
        const chips = Array.from(target.querySelectorAll('.vlan-overview-link'));
        if (chips.length) {
            out.push(text(4, y + 13, overviewTitle, 'h-section'));
            y += 28;
            let x = 0;
            chips.forEach((chipLink) => {
                const chip = chipLink.querySelector('.vlan-overview-card');
                const strong = chip.querySelector('strong');
                const name = strong ? strong.textContent.trim().replace(/:$/, '') : '';
                const count = chip.textContent.replace(strong ? strong.textContent : '', '').trim();
                const width = 30 + textWidth(name, `700 12.5px ${FONT}`) +
                    textWidth(count, `400 12.5px ${FONT}`);
                if (x > 0 && x + width > innerW) {
                    x = 0;
                    y += 38;
                }
                out.push(`<rect x="${x}" y="${y}" width="${width}" height="30" rx="5" fill="#fff" ` +
                    'stroke="#d7dce1" stroke-width="1"/>');
                out.push(`<rect x="${x}" y="${y}" width="5" height="30" fill="#c6cccb"/>`);
                out.push(text(x + 13, y + 19.5, name, 'chip-name'));
                out.push(text(x + 13 + textWidth(name, `700 12.5px ${FONT}`) + 6, y + 19.5, count, 'chip-count'));
                x += width + 8;
            });
            y += 38 + 10;
        }

        out.push(text(4, y + 13, elementsTitle, 'h-section'));
        y += 30;

        target.querySelectorAll('.vlan-parent-card').forEach((card) => {
            const head = card.querySelector('h5');
            const title = head ? head.textContent.trim() : '';
            const fields = fieldList(card);
            const children = Array.from(card.querySelectorAll('.vlan-child-card'));
            const contentX = 21;
            const contentW = innerW - contentX - 10;

            const titleLines = wrap(title, `700 14.5px ${FONT}`, contentW, 2);

            // Pre-compute child cards so the parent grows with its grid.
            const columns = Math.max(1, Math.floor((innerW - 32 + 14) / (280 + 14)));
            const childW = Math.floor((innerW - 32 - (columns - 1) * 14) / columns);
            const childPlans = children.map((child) => {
                const childHead = child.querySelector('h6');
                const childTitle = childHead ? childHead.textContent.trim() : '';
                const childLines = wrap(childTitle, `700 12.5px ${FONT}`, childW - 30, 2);
                const childFields = fieldList(child);
                const probe = [];
                const used = drawFields(probe, childFields, 18, 0, childW - 30, 'c-label', 'c-value', 14, 11.5);
                return {
                    child, childTitle, childLines, childFields,
                    height: 14 + childLines.length * 15 + Math.round(used) + 10,
                };
            });
            const childRows = [];
            for (let i = 0; i < childPlans.length; i += columns) {
                const row = childPlans.slice(i, i + columns);
                childRows.push({ plans: row, height: Math.max(...row.map((plan) => plan.height), 54) });
            }

            const fieldProbeHeight = Math.round(
                drawFields([], fields, contentX, 0, contentW, 'f-label', 'f-value', 16, 12));

            const gridHeight = childRows.reduce((a, row) => a + 10 + row.height + 14, 0);
            const cardHeight = 14 + titleLines.length * 19 + fieldProbeHeight +
                (childRows.length ? gridHeight : 0) + 14;

            out.push(`<rect x="0.5" y="${y}" width="${innerW - 1}" height="${cardHeight}" rx="6" ` +
                'fill="#ffffff" stroke="#d7dce1" stroke-width="1"/>');
            out.push(`<rect x="0" y="${y}" width="5" height="${cardHeight}" fill="#c6cccb"/>`);
            let ty = y + 22;
            titleLines.forEach((line) => {
                out.push(text(contentX, ty, line, 'p-title'));
                ty += 19;
            });
            ty = drawFields(out, fields, contentX, ty, contentW, 'f-label', 'f-value', 16, 12);

            childRows.forEach((row) => {
                let cx = 16;
                ty += 10;
                row.plans.forEach((plan) => {
                    const cy = ty;
                    const accent = locationRgb(plan.child);
                    out.push(`<rect x="${cx}" y="${cy}" width="${childW}" height="${row.height}" rx="5" ` +
                        'fill="#ffffff" stroke="#d7dce1" stroke-width="1"/>');
                    out.push(`<rect x="${cx}" y="${cy}" width="${childW}" height="${row.height}" rx="5" ` +
                        `fill="${accent}" fill-opacity="0.07"/>`);
                    out.push(`<rect x="${cx}" y="${cy}" width="5" height="${row.height}" fill="${accent}"/>`);
                    let childTy = cy + 18;
                    plan.childLines.forEach((line) => {
                        out.push(text(cx + 18, childTy, line, 'c-title'));
                        childTy += 15;
                    });
                    drawFields(out, plan.childFields, cx + 18, childTy, childW - 30, 'c-label', 'c-value', 14, 11.5);
                    cx += childW + 14;
                });
                ty += row.height + 14;
            });

            y += cardHeight + 14;
        });

        return { width: WIDTH, height: y + BOTTOM_PAD, markup: out.join('') };
    }

    /* ------------------------------------------------------------------
       Logical map: the unfolded details tree as an indented outline
       ------------------------------------------------------------------ */

    function drawLogicalTree(target) {
        const root = target.querySelector('details.stage-1');
        const out = [];
        let y = 20;

        function walk(node, depth) {
            const summary = node.querySelector(':scope > summary');
            if (!summary) return;
            const x = 4 + depth * 24;
            const titleX = x + 18;
            const color = getComputedStyle(summary).color || '#333333';
            const titleEl = summary.querySelector('.summary-title');
            const subEl = summary.querySelector('.summary-subtitle');
            const title = titleEl ? titleEl.textContent.trim() : '';
            const sub = subEl ? subEl.textContent.trim() : '';
            const maxWidth = WIDTH - RIGHT_PAD - titleX;

            const midY = y - 4;
            out.push(`<line x1="${x}" y1="${midY}" x2="${x + 11}" y2="${midY}" ` +
                `stroke="${color}" stroke-width="2.5"/>`);

            wrap(title, `700 13.5px ${FONT}`, maxWidth).forEach((line) => {
                out.push(text(titleX, y, line, 'n-title', ` fill="${color}"`));
                y += 17;
            });
            if (sub) {
                wrap(sub, `400 11px ${FONT}`, maxWidth).forEach((line) => {
                    out.push(text(titleX, y + 3, line, 'n-sub'));
                    y += 13;
                });
            }
            y += 3;

            node.querySelectorAll(':scope > .details-content > .info-grid > .info-item')
                .forEach((item) => {
                    const labelEl = item.querySelector('.info-label');
                    const valueEl = item.querySelector('.info-value');
                    if (!labelEl || !valueEl) return;
                    const label = labelEl.textContent.trim();
                    let value = valueEl.textContent.trim().replace(/\s*\p{So}+$/u, '').trim();
                    if (!value) value = '\u2014';
                    const labelWidth = 110;
                    const lines = wrap(value, `400 11.5px ${FONT}`, WIDTH - RIGHT_PAD - titleX - labelWidth - 8);
                    lines.forEach((line, index) => {
                        const lineY = y + (index + 1) * 13 - 3;
                        if (index === 0) {
                            out.push(text(titleX, lineY, label, 'i-label'));
                        }
                        out.push(text(titleX + labelWidth, lineY, line, 'i-value'));
                    });
                    y += lines.length * 13 + 4;
                });

            // Keep every following title a full line below the last row.
            y += 10;
            node.querySelectorAll(':scope > .details-content > details').forEach((child) => {
                walk(child, depth + 1);
            });
        }

        if (root) walk(root, 0);
        else out.push(text(4, y, target.textContent.trim().slice(0, 200) || '\u2014', 'i-value'));
        return { width: WIDTH, height: y + BOTTOM_PAD, markup: out.join('') };
    }

    const RENDERERS = {
        'machine-list': drawMachineList,
        'logical-tree': drawLogicalTree,
    };

    async function exportSvg() {
        const target = document.querySelector(button.dataset.exportTarget || 'body');
        const draw = RENDERERS[button.dataset.exportRenderer];
        if (!target || !draw) return;
        button.disabled = true;
        try {
            const { width, height, markup } = draw(target);
            const source = '<?xml version="1.0" encoding="UTF-8"?>\n' +
                `<svg xmlns="${SVG_NS}" width="${Math.round(width)}" height="${Math.round(height)}" ` +
                `viewBox="0 0 ${Math.round(width)} ${Math.round(height)}">` +
                `<style>${STYLE}</style>` +
                `<rect x="0" y="0" width="${Math.round(width)}" height="${Math.round(height)}" fill="#ffffff"/>` +
                markup + '</svg>';
            const url = URL.createObjectURL(new Blob([source], { type: 'image/svg+xml;charset=utf-8' }));
            const anchor = document.createElement('a');
            anchor.href = url;
            anchor.download = `${button.dataset.exportName || 'export'}_${new Date().toISOString().slice(0, 10)}.svg`;
            anchor.click();
            URL.revokeObjectURL(url);
        } finally {
            button.disabled = false;
        }
    }

    button.addEventListener('click', exportSvg);
})();
