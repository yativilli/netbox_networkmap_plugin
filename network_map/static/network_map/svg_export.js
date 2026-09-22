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
        '.map-border { fill: none; stroke: #c8102e; stroke-width: 2; stroke-dasharray: 8 6; }',
        '.map-border-halo { fill: none; stroke: #ffffff; stroke-width: 7; stroke-opacity: 0.4; }',
        '.map-pin { stroke: #ffffff; stroke-width: 2; }',
        '.map-site { font-size: 11.5px; font-weight: 700; fill: #1f2937; }',
        '.map-legend { font-size: 11.5px; fill: #212529; }',
        '.map-legend-border { fill: none; stroke: #c8102e; stroke-width: 2; stroke-dasharray: 8 6; }',
        '.map-note { font-size: 11px; fill: #6c757d; }',
        '.map-scale { fill: none; stroke: #212529; stroke-width: 1.5; }',
        '.map-scale-label { font-size: 10px; fill: #212529; }',
        '.map-offframe { fill: #6c757d; stroke: #ffffff; stroke-width: 1.5; }',
        '.map-plan { fill: #f8f5ec; stroke: #8a8378; stroke-width: 2; }',
        '.map-tip { fill: rgba(255, 255, 255, 0.92); stroke: #ced4da; stroke-width: 1; }',
        '.map-tip-site { font-size: 11px; font-weight: 700; fill: #212529; }',
        '.map-tip-sub { font-size: 10.5px; fill: #6c757d; }',
        '.map-machine { stroke-width: 2; }',
        '.map-machine.is-vm { stroke-width: 3; }',
        '.map-machine-name { font-size: 10.5px; font-weight: 700; fill: #1f2937;',
        '  paint-order: stroke; stroke: #ffffff; stroke-width: 3px; }',
        '.map-machine-ip { font-size: 9.5px; fill: #6c757d;',
        '  paint-order: stroke; stroke: #ffffff; stroke-width: 3px; }',
        '.map-machine-num { font-size: 9.5px; font-weight: 700; fill: #ffffff;',
        '  text-anchor: middle; paint-order: stroke;',
        '  stroke: rgba(0, 0, 0, 0.45); stroke-width: 2px; }',
        '.map-machine-num.is-vm { fill: #1f2937; stroke: #ffffff; }',
        '.map-list-name { font-size: 10.5px; font-weight: 700; }',
        '.map-list-sub { font-size: 10px; fill: #6c757d; }',
        '.map-attribution { font-size: 10px; fill: #6c757d; }',
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
                out.push(text(titleX, y, line, 'n-title', ` style="fill:${color}"`));
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

    /* ------------------------------------------------------------------
       Subnet map: the current viewport, tiles fetched anew so the
       export can embed them without tainting the canvas
       ------------------------------------------------------------------ */

    const MAP_PIN_R = 6;
    const MAP_PIN_STEP = 15;
    const MAP_PIN_COLS = 6;
    const MAP_MAX_TILES = 64;
    const SCALE_STEPS_M = [100, 200, 500, 1000, 2000, 5000, 10000, 20000, 50000, 100000];

    function mapRings(geojson) {
        const rings = [];
        (geojson.features || []).forEach((feature) => {
            const geometry = feature.geometry || {};
            if (geometry.type === 'Polygon') rings.push(...geometry.coordinates);
            if (geometry.type === 'MultiPolygon') {
                geometry.coordinates.forEach((polygon) => rings.push(...polygon));
            }
        });
        return rings.filter((ring) => ring.length > 2);
    }

    function mapBorderPath(rings, project) {
        const parts = [];
        rings.forEach((ring) => {
            ring.forEach((position, index) => {
                const p = project([Number(position[1]), Number(position[0])]);
                parts.push(`${index ? 'L' : 'M'}${p.x.toFixed(1)},${p.y.toFixed(1)}`);
            });
            parts.push('Z');
        });
        return parts.join('');
    }

    // The live tiles are drawn cross origin, which taints the canvas, so the
    // same URLs are fetched again (plain CORS GET) and re-encoded. When the
    // tile server refuses, the export stays vector-only.
    async function rasterizeTiles(entries) {
        const images = [];
        for (const entry of entries.slice(0, MAP_MAX_TILES)) {
            const url = entry.img.currentSrc || entry.img.src;
            if (!url || url.startsWith('data:')) continue;
            try {
                const response = await fetch(url, { mode: 'cors', credentials: 'omit' });
                if (!response.ok) continue;
                const objectUrl = URL.createObjectURL(await response.blob());
                const image = await new Promise((resolve, reject) => {
                    const loaded = new Image();
                    loaded.onload = () => resolve(loaded);
                    loaded.onerror = () => reject(new Error('tile load failed'));
                    loaded.src = objectUrl;
                });
                const canvas = document.createElement('canvas');
                canvas.width = image.naturalWidth;
                canvas.height = image.naturalHeight;
                canvas.getContext('2d').drawImage(image, 0, 0);
                URL.revokeObjectURL(objectUrl);
                images.push({
                    x: entry.x, y: entry.y, width: entry.w, height: entry.h,
                    href: canvas.toDataURL('image/jpeg', 0.82)
                });
            } catch (error) {
                // No CORS on the tile server: keep the export vector-only.
            }
        }
        return images;
    }

    function mapClusters(pins) {
        const clusters = new Map();
        pins.forEach((pin) => {
            const key = `${pin.lat.toFixed(5)},${pin.lon.toFixed(5)}`;
            if (!clusters.has(key)) clusters.set(key, { site: pin.site, pins: [] });
            clusters.get(key).pins.push(pin);
        });
        return Array.from(clusters.values());
    }

    // Metres per exported pixel and a bar of a round length for it. A
    // stretched plan (mapScale > 1) shrinks the ground one pixel covers.
    function scaleBar(map, frame, mapScale) {
        const step = 100;
        const y = frame.y + frame.height - 20 / mapScale;
        const from = map.containerPointToLatLng([frame.x, y]);
        const to = map.containerPointToLatLng([frame.x + step, y]);
        const perPixel = from.distanceTo(to) / step / mapScale;
        const wanted = perPixel * 120;
        const metres = SCALE_STEPS_M.find((value) => value >= wanted) ||
            SCALE_STEPS_M[SCALE_STEPS_M.length - 1];
        const bar = metres / perPixel;
        return { bar, label: metres >= 1000 ? `${metres / 1000} km` : `${metres} m` };
    }

    function mapCrop(map, size, boundary) {
        const full = {x: 0, y: 0, width: size.x, height: size.y};
        if (!boundary) return full;
        let bounds;
        try {
            bounds = L.geoJSON(boundary).getBounds();
        } catch (error) {
            return full;
        }
        if (!bounds.isValid() || !map.getBounds().contains(bounds)) return full;
        const nw = map.latLngToContainerPoint(bounds.getNorthWest());
        const se = map.latLngToContainerPoint(bounds.getSouthEast());
        const inset = 12;
        return {
            x: nw.x - inset, y: nw.y - inset,
            width: se.x - nw.x + 2 * inset, height: se.y - nw.y + 2 * inset
        };
    }

    // The floor plan lives as inline SVG in the overlay pane; copy it into
    // the export at the same place and size. Uploaded plans reference
    // MEDIA_URL files relatively, which a standalone file must resolve.
    // The plan frame is projected, not measured: it uses the very same
    // transform the machine dots are placed with, so the two cannot drift
    // apart after a panel toggle, a map resize or a page scroll.
    function planRect(house, toExport) {
        if (!house || !house.bounds) return null;
        const nw = toExport(L.latLng(house.bounds.n, house.bounds.w));
        const se = toExport(L.latLng(house.bounds.s, house.bounds.e));
        return {x: nw.x, y: nw.y, width: se.x - nw.x, height: se.y - nw.y};
    }

    function planGraphics(container, house, rect) {
        const node = container.querySelector('.house-plan-overlay');
        if (!node || !rect) return '';
        const origin = window.location.origin;
        const inner = node.innerHTML
            .replace(/href="(\/[^"]*)"/g, `href="${origin}$1"`)
            .replace(/xlink:href="(\/[^"]*)"/g, `xlink:href="${origin}$1"`);
        const viewBox = node.getAttribute('viewBox') ||
            `0 0 ${house.planW || rect.width} ${house.planH || rect.height}`;
        const x = rect.x.toFixed(1);
        const y = rect.y.toFixed(1);
        const w = rect.width.toFixed(1);
        const h = rect.height.toFixed(1);
        // "meet" letterboxes the drawing inside the frame, exactly like the
        // overlay does on screen.
        return `<rect class="map-plan" x="${x}" y="${y}" width="${w}" height="${h}"/>` +
            `<svg x="${x}" y="${y}" width="${w}" height="${h}" viewBox="${viewBox}" ` +
            `preserveAspectRatio="xMidYMid meet">${inner}</svg>`;
    }

    // Labels are always exported, also while the page hides them: the file
    // is meant to be read on its own.
    function pinLabel(out, x, y, site, sub) {
        const siteFont = `700 11px ${FONT}`;
        const subFont = `400 10.5px ${FONT}`;
        const siteText = clipTo(site, siteFont, 180);
        const subText = clipTo(sub, subFont, 180);
        const boxW = Math.max(textWidth(siteText, siteFont), textWidth(subText, subFont)) + 12;
        out.push(
            `<rect class="map-tip" x="${(x - boxW / 2).toFixed(1)}" y="${y.toFixed(1)}" ` +
            `width="${boxW.toFixed(1)}" height="27" rx="4"/>`
        );
        out.push(text(Math.round(x - boxW / 2 + 6), y + 11, siteText, 'map-tip-site'));
        out.push(text(Math.round(x - boxW / 2 + 6), y + 23, subText, 'map-tip-sub'));
    }

    function clipTo(value, font, maxWidth) {
        const text2 = String(value || '');
        if (textWidth(text2, font) <= maxWidth) return text2;
        let cut = text2;
        while (cut.length > 1 && textWidth(`${cut}\u2026`, font) > maxWidth) cut = cut.slice(0, -1);
        return `${cut.replace(/[\s.,;:)+/-]+$/, '')}\u2026`;
    }

    // A machine label is its name over its IP; the export stretches the
    // floor plan until every dot has that much room, so the labels cannot
    // touch. Only when even MAX_MAP_SCALE is not enough are the dots
    // numbered and the machines listed beside the map instead.
    const MAX_MAP_SCALE = 12;
    const PLAN_MARGIN = 28;
    const MACHINE_LABEL_HEIGHT = 26;
    const MACHINE_BADGE = 26;
    // A plan exported at its on-screen size is cramped on paper, so it is
    // always grown to this long edge before anything else is considered.
    const MIN_PLAN_EDGE = 1100;
    const MACHINE_LABEL_MIN_AREA = 3400;
    // Lettering inside the generated logical plan (its room labels) and the
    // limit for the export's own text, so neither can dwarf the other.
    const PLAN_TEXT_PX = 17;
    const LABEL_TEXT_PX = 10.5;
    const MAX_TEXT_SCALE = 4;

    // Everything the export itself draws - dot badges, labels, legend,
    // machine list - grows with the plan it annotates, so the picture keeps
    // one typographic scale instead of a huge plan above tiny print.
    let TF = 1;
    const px = (base) => String(+(base * TF).toFixed(2));
    const nameFont = () => `700 ${px(10.5)}px ${FONT}`;
    const ipFont = () => `400 ${px(9.5)}px ${FONT}`;
    const listNameFont = () => `700 ${px(10.5)}px ${FONT}`;
    const listSubFont = () => `400 ${px(10)}px ${FONT}`;

    // Room a label has before it hits a neighbour, measured on the dots
    // themselves: dots in a row decide the width, dots below each other the
    // height. Infinity when there is no such neighbour.
    function machineSpacing(points) {
        const gaps = { x: Infinity, y: Infinity, d: Infinity };
        points.forEach((a, index) => {
            points.slice(index + 1).forEach((b) => {
                const dx = Math.abs(a.x - b.x);
                const dy = Math.abs(a.y - b.y);
                if (dy < 8 && dx > 0.5) gaps.x = Math.min(gaps.x, dx);
                if (dx < 8 && dy > 0.5) gaps.y = Math.min(gaps.y, dy);
                gaps.d = Math.min(gaps.d, Math.hypot(dx, dy));
            });
        });
        return gaps;
    }

    function machineLabelsNeed(machines) {
        const width = machines.reduce((widest, machine) => Math.max(
            widest,
            textWidth(String(machine.name || ''), nameFont()),
            textWidth(String(machine.ip || ''), ipFont())
        ), 0) + 10 * TF;
        const height = MACHINE_LABEL_HEIGHT * TF;
        return {
            width,
            height,
            area: Math.max(MACHINE_LABEL_MIN_AREA * TF * TF, width * height)
        };
    }

    // How much the plan's own lettering is magnified in the export; the
    // export's text aims at the same rendered size.
    function planTextFactor(frame, scale, house) {
        if (!house || !house.planW) return 1;
        const perUnit = (frame.width * scale) / house.planW;
        return Math.min(MAX_TEXT_SCALE, Math.max(1,
            perUnit * PLAN_TEXT_PX / LABEL_TEXT_PX));
    }

    // How far the plan must grow. Numbered dots only need room for their
    // badge; carrying "name / IP" labels next to every dot needs a lot more,
    // so a plan too dense for that is not inflated for nothing.
    function planStretch(frame, need, gaps, count, withLabels) {
        const area = Math.max(1, frame.width * frame.height);
        const badge = MACHINE_BADGE * TF;
        const candidates = [
            1,
            MIN_PLAN_EDGE / Math.max(frame.width, frame.height),
            Math.sqrt((badge * badge * Math.max(1, count)) / area),
            Number.isFinite(gaps.d) ? badge / gaps.d : 1
        ];
        if (withLabels) {
            candidates.push(
                Math.sqrt((need.area * Math.max(1, count)) / area),
                Number.isFinite(gaps.x) ? need.width / gaps.x : 1,
                Number.isFinite(gaps.y) ? need.height / gaps.y : 1
            );
        }
        return Math.min(MAX_MAP_SCALE, Math.max(...candidates));
    }

    // Plan magnification, text factor and label verdict settle together: the
    // text follows the plan, the plan follows the text. Three passes are
    // enough because both converge from the same direction.
    function solvePlan(frame, gaps, machines, house, withLabels) {
        let scale = 1;
        for (let pass = 0; pass < 3; pass += 1) {
            TF = planTextFactor(frame, scale, house);
            scale = planStretch(frame, machineLabelsNeed(machines), gaps,
                machines.length, withLabels);
        }
        TF = planTextFactor(frame, scale, house);
        return {
            scale,
            textFactor: TF,
            crowded: labelsStillCrowded(frame, machineLabelsNeed(machines), gaps,
                scale, machines.length)
        };
    }

    // Numbered badges may not overlap. Rather than inflating the whole plan
    // until the closest pair of dots has room, the dots that sit too close
    // are nudged apart; the plan keeps its computed size.
    function spreadOut(points, minDistance, bounds) {
        if (!(minDistance > 0) || points.length < 2) return points;
        const anchors = points.map((point) => ({ x: point.x, y: point.y }));
        for (let pass = 0; pass < 12; pass += 1) {
            let moved = false;
            for (let i = 0; i < points.length; i += 1) {
                for (let j = i + 1; j < points.length; j += 1) {
                    const dx = points[j].x - points[i].x;
                    const dy = points[j].y - points[i].y;
                    const distance = Math.hypot(dx, dy);
                    if (distance >= minDistance) continue;
                    const push = ((minDistance - distance) / 2) || 0.5;
                    const ux = distance ? dx / distance : (i % 2 ? 1 : -1);
                    const uy = distance ? dy / distance : 0;
                    points[i].x -= ux * push;
                    points[i].y -= uy * push;
                    points[j].x += ux * push;
                    points[j].y += uy * push;
                    moved = true;
                }
            }
            // A dot may leave its slot to make room for a neighbour, but it
            // must not wander across the plan: every pass pulls it back.
            points.forEach((point, index) => {
                point.x += (anchors[index].x - point.x) * 0.1;
                point.y += (anchors[index].y - point.y) * 0.1;
            });
            if (!moved) break;
        }
        if (bounds) {
            points.forEach((point) => {
                point.x = Math.min(Math.max(point.x, bounds.x), bounds.x + bounds.width);
                point.y = Math.min(Math.max(point.y, bounds.y), bounds.y + bounds.height);
            });
        }
        return points;
    }

    function labelsStillCrowded(frame, need, gaps, scale, count) {
        if (!frame || count === 0) return false;
        if ((frame.width * frame.height * scale * scale) / count < need.area) return true;
        if (Number.isFinite(gaps.x) && gaps.x * scale < need.width) return true;
        return Number.isFinite(gaps.y) && gaps.y * scale < need.height;
    }

    function drawMachines(house, toExport, numbered, bounds, out) {
        const machines = (house.machines || []).filter(
            (machine) => machine.lat != null && machine.lng != null);
        const points = spreadOut(
            machines.map((machine) => toExport(L.latLng(machine.lat, machine.lng))),
            numbered ? MACHINE_BADGE * TF : 0, bounds);
        machines.forEach((machine, index) => {
            const p = points[index];
            const fill = machine.physical ? (machine.color || '#6c757d') : '#ffffff';
            out.push(
                `<circle class="map-machine${machine.physical ? '' : ' is-vm'}" ` +
                `cx="${p.x.toFixed(1)}" cy="${p.y.toFixed(1)}" ` +
                `r="${((numbered ? 9 : 7) * TF).toFixed(1)}" fill="${fill}" ` +
                `stroke="${machine.color || '#6c757d'}"/>`
            );
            if (numbered) {
                out.push(text(Math.round(p.x), Math.round(p.y + 3 * TF), index + 1,
                    `map-machine-num${machine.physical ? '' : ' is-vm'}`));
                return;
            }
            const middle = ' text-anchor="middle"';
            out.push(text(Math.round(p.x), Math.round(p.y - 13 * TF), machine.name,
                'map-machine-name', middle));
            out.push(text(Math.round(p.x), Math.round(p.y - 3 * TF), machine.ip,
                'map-machine-ip', middle));
        });
    }

    // Numbered machines listed in columns, keeping the dot's colour coding:
    // the badge number and name in the machine's colour, its description and
    // IP address underneath.
    function machineList(machines, width, startY, out) {
        if (!machines.length) return startY;
        const colWidth = 320 * TF;
        const rowHeight = 30 * TF;
        const columns = Math.max(1, Math.floor(width / colWidth));
        const perColumn = Math.ceil(machines.length / columns);
        let rows = 0;
        machines.forEach((machine, index) => {
            const x = 24 * TF + Math.floor(index / perColumn) * colWidth;
            const y = startY + (index % perColumn) * rowHeight;
            rows = Math.max(rows, (index % perColumn) + 1);
            const color = machine.color || '#6c757d';
            const fill = machine.physical ? color : '#ffffff';
            out.push(
                `<circle class="map-machine${machine.physical ? '' : ' is-vm'}" ` +
                `cx="${(x + 6 * TF).toFixed(1)}" cy="${(y - 4 * TF).toFixed(1)}" ` +
                `r="${(6 * TF).toFixed(1)}" fill="${fill}" stroke="${color}"/>`
            );
            const label = `${index + 1}  ${machine.name}${machine.physical ? '' : ' (VM)'}`;
            out.push(text(x + 20 * TF, y, clipTo(label, listNameFont(), colWidth - 34 * TF),
                'map-list-name', ` style="fill:${color}"`));
            const sub = [machine.description, machine.ip].filter(Boolean).join(' — ');
            out.push(text(x + 20 * TF, y + 12 * TF,
                clipTo(sub, listSubFont(), colWidth - 34 * TF), 'map-list-sub'));
        });
        return startY + rows * rowHeight + 6 * TF;
    }

    async function drawSubnetMap() {
        const map = window.__subnetMap;
        const container = document.getElementById('subnet-map');
        const dataNode = document.getElementById('subnet-map-data');
        if (!map || !container || !dataNode) {
            return { width: 1, height: 1, markup: '' };
        }
        const data = JSON.parse(dataNode.textContent);
        TF = 1;
        const pins = data.pins || [];
        const house = window.__subnetMapHouse;
        const boundary = window.__subnetMapBoundary;
        const origin = container.getBoundingClientRect();
        const size = map.getSize();
        const machines = house
            ? (house.machines || []).filter((m) => m.lat != null && m.lng != null)
            : [];

        // A floor plan is stretched until every machine has room for its
        // label, so a dense plan comes out larger instead of turning its
        // labels into noise. Region views keep the screen's scale.
        const rawProject = (latlng) => map.latLngToContainerPoint(latlng);
        const rawFrame = house ? planRect(house, rawProject) : null;
        let mapScale = 1;
        let crowded = false;
        let frame;
        if (rawFrame) {
            frame = {
                x: rawFrame.x - PLAN_MARGIN, y: rawFrame.y - PLAN_MARGIN,
                width: rawFrame.width + 2 * PLAN_MARGIN,
                height: rawFrame.height + 2 * PLAN_MARGIN
            };
            const gaps = machineSpacing(machines.map(
                (machine) => rawProject(L.latLng(machine.lat, machine.lng))));
            // Labels are tried first; when they cannot be placed without
            // touching, the plan is sized for numbered badges alone.
            const labelled = solvePlan(rawFrame, gaps, machines, house, true);
            crowded = labelled.crowded;
            const plan = crowded
                ? solvePlan(rawFrame, gaps, machines, house, false)
                : labelled;
            mapScale = plan.scale;
            TF = plan.textFactor;
        } else {
            frame = house
                ? {x: 0, y: 0, width: size.x, height: size.y}
                : mapCrop(map, size, boundary);
        }
        const width = frame.width * mapScale;
        const height = frame.height * mapScale;
        const toExport = (latlng) => {
            const p = map.latLngToContainerPoint(latlng);
            return {x: (p.x - frame.x) * mapScale, y: (p.y - frame.y) * mapScale};
        };

        const tileEntries = [];
        container.querySelectorAll('.leaflet-tile-pane img').forEach((img) => {
            const box = img.getBoundingClientRect();
            if (box.right < frame.x || box.bottom < frame.y ||
                box.left > frame.x + frame.width || box.top > frame.y + frame.height) return;
            tileEntries.push({
                img,
                x: (box.left - origin.left - frame.x) * mapScale,
                y: (box.top - origin.top - frame.y) * mapScale,
                w: box.width * mapScale,
                h: box.height * mapScale
            });
        });
        const tiles = await rasterizeTiles(tileEntries);

        const out = [];
        out.push(
            `<rect x="0" y="0" width="${width.toFixed(1)}" height="${height.toFixed(1)}" ` +
            `fill="${house ? '#f8f5ec' : '#eef1f4'}"/>`
        );
        tiles.forEach((tile) => {
            out.push(
                `<image href="${tile.href}" xlink:href="${tile.href}" ` +
                `x="${tile.x.toFixed(1)}" y="${tile.y.toFixed(1)}" ` +
                `width="${tile.w.toFixed(1)}" height="${tile.h.toFixed(1)}"/>`
            );
        });
        const planFrame = rawFrame ? planRect(house, toExport) : null;
        if (house) {
            out.push(planGraphics(container, house, planFrame));
        } else {
            const rings = mapRings(boundary || { features: [] });
            if (rings.length) {
                const path = mapBorderPath(rings, toExport);
                out.push(`<path class="map-border-halo" d="${path}"/>`);
                out.push(`<path class="map-border" d="${path}"/>`);
            }
        }

        let outside = 0;
        const numbered = house && crowded ? machines : [];
        if (house) {
            drawMachines(house, toExport, crowded,
                { x: 0, y: 0, width, height }, out);
        } else {
            mapClusters(pins).forEach((cluster) => {
                const point = toExport(L.latLng(cluster.pins[0].lat, cluster.pins[0].lon));
                const inset = MAP_PIN_R + 4;
                const clamped = point.x < 0 || point.y < 0 ||
                    point.x > width || point.y > height;
                const x = Math.min(Math.max(point.x, inset), width - inset);
                const y = Math.min(Math.max(point.y, inset), height - inset);
                if (clamped) {
                    outside += 1;
                    out.push(
                        `<circle class="map-offframe" cx="${x.toFixed(1)}" ` +
                        `cy="${y.toFixed(1)}" r="4"/>`
                    );
                    return;
                }
                const cols = Math.min(MAP_PIN_COLS, cluster.pins.length);
                const rows = Math.ceil(cluster.pins.length / cols);
                cluster.pins.forEach((pin, index) => {
                    const dx = ((index % cols) - (cols - 1) / 2) * MAP_PIN_STEP;
                    const dy = (Math.floor(index / cols) - (rows - 1) / 2) * MAP_PIN_STEP;
                    out.push(
                        `<circle class="map-pin" cx="${(x + dx).toFixed(1)}" ` +
                        `cy="${(y + dy).toFixed(1)}" r="${MAP_PIN_R}" ` +
                        `fill="${pin.color || '#6c757d'}"/>`
                    );
                });
                const sub = cluster.pins.map((pin) => pin.prefix || pin.subnet).join(', ');
                pinLabel(out, x, y + ((rows - 1) * MAP_PIN_STEP) / 2 + 10, cluster.site, sub);
            });
        }

        const scale = scaleBar(map, frame, mapScale);
        out.push(
            `<path class="map-scale" d="M${12 * TF},${(height - 16 * TF).toFixed(1)} ` +
            `v${-6 * TF} H${(12 * TF + scale.bar).toFixed(1)} v${-6 * TF}"/>`
        );
        out.push(text(Math.round(18 * TF + scale.bar), Math.round(height - 16 * TF),
            scale.label, 'map-scale-label'));

        // A floor plan only ever shows one site, so its legend lists just
        // the subnets that are visible on it.
        const legendPins = house ? pins.filter((pin) => pin.site === house.site) : pins;
        const seen = new Set();
        const entries = legendPins.filter((pin) => {
            const key = `${pin.color}|${pin.subnet}|${pin.prefix}`;
            if (seen.has(key)) return false;
            seen.add(key);
            return true;
        });
        // Numbered lists want more width than a narrow plan strip offers.
        const listColumns = numbered.length
            ? Math.max(1, Math.min(4, Math.ceil(numbered.length / 40)))
            : 1;
        const listWidth = (listColumns * 320 + 24) * TF;
        const outWidth = Math.max(width, listWidth);
        const step = 16 * TF;
        let y = height + 26 * TF;
        y = machineList(numbered, listWidth, y, out);
        entries.slice(0, 14).forEach((pin) => {
            const value = pin.prefix ? `${pin.subnet} — ${pin.prefix}` : pin.subnet;
            out.push(
                `<circle class="map-pin" cx="${30 * TF}" cy="${(y - 4 * TF).toFixed(1)}" ` +
                `r="${((MAP_PIN_R - 1) * TF).toFixed(1)}" ` +
                `fill="${pin.color || '#6c757d'}"/>`
            );
            out.push(text(42 * TF, y, value, 'map-legend'));
            y += step;
        });
        if (entries.length > 14) {
            const further = (data.ui || {}).export_further_subnets ||
                '… further subnets not listed';
            out.push(text(42 * TF, y, `… ${entries.length - 14} ${further}`, 'map-note'));
            y += step;
        }
        if (data.canton_label && !house) {
            out.push(`<path class="map-legend-border" d="M${24 * TF},${(y - 4 * TF).toFixed(1)} ` +
                `h${14 * TF}"/>`);
            out.push(text(46 * TF, y, data.canton_label, 'map-legend'));
            y += step;
        }
        if (outside) {
            const outsideLabel = (data.ui || {}).export_outside_area ||
                'site(s) outside the drawn area';
            out.push(text(42 * TF, y, `${outside} ${outsideLabel}`, 'map-note'));
            y += step;
        }
        out.push(text(
            24 * TF, y + 12 * TF,
            (data.ui || {}).attribution || 'Map data: © swisstopo',
            'map-attribution'
        ));
        // A floor plan is a drawing meant to be printed at any size; the
        // regional map is a picture of map tiles, which comes out as PNG.
        return {
            width: outWidth, height: y + 26 * TF, markup: out.join(''),
            format: house ? 'svg' : 'png'
        };
    }

    const RENDERERS = {
        'machine-list': drawMachineList,
        'logical-tree': drawLogicalTree,
        'subnet-map': drawSubnetMap,
    };

    // Rasterising multiplies the canvas, because a canton map printed at its
    // natural size has labels too small to read; browsers cap canvas sizes,
    // so the factor shrinks for very large pictures.
    const PNG_SCALE = 2;
    const PNG_MAX_EDGE = 12000;

    function rasterize(source, width, height) {
        const scale = Math.min(PNG_SCALE, PNG_MAX_EDGE / Math.max(width, height, 1));
        return new Promise((resolve, reject) => {
            const image = new Image();
            const url = URL.createObjectURL(new Blob([source], { type: 'image/svg+xml;charset=utf-8' }));
            image.onload = () => {
                try {
                    const canvas = document.createElement('canvas');
                    canvas.width = Math.max(1, Math.round(width * scale));
                    canvas.height = Math.max(1, Math.round(height * scale));
                    const ctx = canvas.getContext('2d');
                    ctx.fillStyle = '#ffffff';
                    ctx.fillRect(0, 0, canvas.width, canvas.height);
                    ctx.scale(scale, scale);
                    ctx.drawImage(image, 0, 0);
                    URL.revokeObjectURL(url);
                    canvas.toBlob(
                        (blob) => (blob ? resolve(blob) : reject(new Error('PNG encoding failed'))),
                        'image/png'
                    );
                } catch (error) {
                    URL.revokeObjectURL(url);
                    reject(error);
                }
            };
            image.onerror = () => {
                URL.revokeObjectURL(url);
                reject(new Error('SVG could not be rasterised'));
            };
            image.src = url;
        });
    }

    // Sizes live in the stylesheet, so the whole picture - plan and text -
    // is generated at one scale instead of mixing magnified plans with
    // footnote-sized legends.
    function styleSheet(scale) {
        if (scale === 1) return STYLE;
        return STYLE
            .replace(/(font-size): ([\d.]+)px/g,
                (all, property, value) => `${property}: ${(value * scale).toFixed(2)}px`)
            .replace(/(stroke-width): ([\d.]+)(?=[;}\s])/g,
                (all, property, value) => `${property}: ${(value * scale).toFixed(2)}`);
    }

    function dataExportFailed() {
        const node = document.getElementById('subnet-map-data');
        if (!node) return '';
        try {
            return (JSON.parse(node.textContent).ui || {}).export_failed || '';
        } catch (error) {
            return '';
        }
    }

    async function exportSvg() {
        const target = document.querySelector(button.dataset.exportTarget || 'body');
        const draw = RENDERERS[button.dataset.exportRenderer];
        if (!target || !draw) return;
        button.disabled = true;
        try {
            const { width, height, markup, format } = await draw(target);
            const source = '<?xml version="1.0" encoding="UTF-8"?>\n' +
                `<svg xmlns="${SVG_NS}" xmlns:xlink="http://www.w3.org/1999/xlink" ` +
                `width="${Math.round(width)}" height="${Math.round(height)}" ` +
                `viewBox="0 0 ${Math.round(width)} ${Math.round(height)}">` +
                `<style>${styleSheet(TF)}</style>` +
                `<rect x="0" y="0" width="${Math.round(width)}" height="${Math.round(height)}" fill="#ffffff"/>` +
                markup + '</svg>';
            let blob = null;
            let extension = 'svg';
            if (format === 'png') {
                try {
                    blob = await rasterize(source, width, height);
                    extension = 'png';
                } catch (error) {
                    // Some browsers refuse to rasterise very large pictures;
                    // the vector file holds the identical content.
                    console.error('PNG export failed', error);
                }
            }
            if (!blob) {
                blob = new Blob([source], { type: 'image/svg+xml;charset=utf-8' });
            }
            const url = URL.createObjectURL(blob);
            const anchor = document.createElement('a');
            anchor.href = url;
            anchor.download = `${button.dataset.exportName || 'export'}_` +
                `${new Date().toISOString().slice(0, 10)}.${extension}`;
            anchor.click();
            URL.revokeObjectURL(url);
        } catch (error) {
            console.error('export failed', error);
            window.alert((dataExportFailed() || 'The export could not be created') +
                `\n${error && error.message ? error.message : error}`);
        } finally {
            button.disabled = false;
        }
    }

    button.addEventListener('click', exportSvg);
})();
