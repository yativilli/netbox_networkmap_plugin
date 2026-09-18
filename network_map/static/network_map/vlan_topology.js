(function () {
    const stage = document.getElementById('vlan-topology-stage');
    const viewport = document.querySelector('.vlan-topology-viewport');
    const controls = Array.from(document.querySelectorAll('[data-zoom]'));

    const state = { scale: 1, tx: 0, ty: 0, dragging: false, dragStartX: 0, dragStartY: 0, startTx: 0, startTy: 0 };

    const SVG_NS = 'http://www.w3.org/2000/svg';

    const HUB_R = 60;
    const SUB_W = 150;
    const SUB_H = 110;
    const SUB_DIAG = Math.hypot(SUB_W / 2, SUB_H / 2);
    const MACH_R = 42;
    const GAP = 2.5;
    const MIN_SEP = MACH_R * 2 + GAP * 2;
    const R0 = 140;
    const RING_STEP = 95;
    const MIN_HUB_DIST = 265;
    const PAD = 40;

    function clamp(value, min, max) {
        return Math.min(Math.max(value, min), max);
    }

    function svgEl(name, attrs) {
        const el = document.createElementNS(SVG_NS, name);
        Object.entries(attrs || {}).forEach(([key, value]) => el.setAttribute(key, value));
        return el;
    }

    function linkEl(href, cls) {
        const link = svgEl('a', { class: cls, href: href || '#' });
        link.setAttribute('target', '_blank');
        link.setAttribute('rel', 'noopener');
        return link;
    }

    function wrapLines(text, maxChars, maxLines) {
        const source = String(text || '');
        const words = source.split(/\s+/).filter(Boolean);
        const lines = [];
        let current = '';
        words.forEach((word) => {
            const candidate = current ? `${current} ${word}` : word;
            if (candidate.length <= maxChars) {
                current = candidate;
                return;
            }
            if (current) lines.push(current);
            current = word.length > maxChars ? `${word.slice(0, maxChars - 1)}\u2026` : word;
        });
        if (current) lines.push(current);
        if (!lines.length) lines.push(source || '');
        if (lines.length > maxLines) {
            const kept = lines.slice(0, maxLines);
            kept[maxLines - 1] = `${kept[maxLines - 1].replace(/\u2026$/, '')}\u2026`;
            return kept;
        }
        return lines;
    }

    function addText(parent, cls, x, y, lines, lineHeight) {
        const text = svgEl('text', { x, 'text-anchor': 'middle', class: cls });
        const first = y - ((lines.length - 1) * lineHeight) / 2;
        lines.forEach((line, index) => {
            const span = svgEl('tspan', { x, y: first + index * lineHeight });
            span.textContent = line;
            text.appendChild(span);
        });
        parent.appendChild(text);
    }

    function machineRings(count) {
        if (!count) return [];
        const rings = [];
        let radius = R0;
        let capacity = 0;
        while (capacity < count) {
            const cap = Math.max(1, Math.floor((2 * Math.PI * radius) / MIN_SEP));
            rings.push({ radius, cap, count: 0 });
            capacity += cap;
            radius += RING_STEP;
        }
        let assigned = 0;
        let index = 0;
        while (assigned < count) {
            const ring = rings[index % rings.length];
            if (ring.count < ring.cap) {
                ring.count += 1;
                assigned += 1;
            }
            index += 1;
        }
        return rings.filter((ring) => ring.count > 0);
    }

    function clusterFootprint(plan) {
        const machineReach = plan.length ? plan[plan.length - 1].radius + MACH_R + GAP : 0;
        return Math.max(machineReach, SUB_DIAG + GAP);
    }

    // Biggest clusters claim slots along the golden angle first, so
    // comparably sized clusters never sit adjacent; smaller clusters
    // fill the gaps evenly around the circle.
    function goldenSlots(subnets) {
        const bySize = subnets
            .map((subnet, index) => index)
            .sort((a, b) => subnets[b].machines.length - subnets[a].machines.length);
        const slots = new Array(subnets.length).fill(null);
        bySize.forEach((subnetIndex, rank) => {
            let slot = Math.floor((((rank + 1) * 0.6180339887) % 1) * subnets.length);
            while (slots[slot] !== null) slot = (slot + 1) % subnets.length;
            slots[slot] = subnets[subnetIndex];
        });
        return slots;
    }

    // Iteratively push oversized clusters further out along the ring
    // until every pair keeps `clearance` of free space. Mutates radii.
    function resolveCollisions({ radii, footprints, pushedOut, angleAt, clearance }) {
        for (let pass = 0; pass < 500; pass += 1) {
            let moved = false;
            for (let i = 0; i < radii.length; i += 1) {
                for (let j = i + 1; j < radii.length; j += 1) {
                    if (!pushedOut[i] && !pushedOut[j]) continue;
                    const reach = footprints[i] + footprints[j] + clearance;
                    const delta = angleAt(i) - angleAt(j);
                    const da = Math.cos(delta);
                    const sa = Math.sin(delta);
                    const di = radii[i];
                    const dj = radii[j];
                    const dist2 = di * di + dj * dj - 2 * di * dj * da;
                    if (dist2 >= reach * reach) continue;
                    if (pushedOut[i] && pushedOut[j] && Math.abs(footprints[i] - footprints[j]) < 1e-6) {
                        const scale = (reach + 0.01) / Math.sqrt(Math.max(dist2, 1));
                        radii[i] = di * scale;
                        radii[j] = dj * scale;
                    } else if (pushedOut[i] && (!pushedOut[j] || footprints[i] >= footprints[j])) {
                        radii[i] = Math.max(di, dj * da + Math.sqrt(Math.max(0, reach * reach - dj * dj * sa * sa)) + 0.01);
                    } else {
                        radii[j] = Math.max(dj, di * da + Math.sqrt(Math.max(0, reach * reach - di * di * sa * sa)) + 0.01);
                    }
                    moved = true;
                }
            }
            if (!moved) break;
        }
    }

    function buildGraph() {
        if (!stage) return;
        const dataEl = document.getElementById('vlan-topology-data');
        if (!dataEl) return;
        const data = JSON.parse(dataEl.textContent);
        const subnets = data.subnets || [];

        stage.querySelectorAll('svg').forEach((node) => node.remove());
        if (!subnets.length) return;

        const ordered = goldenSlots(subnets);

        const plans = ordered.map((subnet) => machineRings(subnet.machines.length));
        const footprints = plans.map(clusterFootprint);

        const count = ordered.length;
        const angleAt = (index) => -Math.PI / 2 + (index * 2 * Math.PI) / count;

        // Every subnet shares one common ring, including the ones without any
        // machines. Clusters bigger than the median never fit on that ring;
        // they are pushed out only as far as needed to keep PUSH_CLEARANCE of
        // free space to everything else.
        const PUSH_CLEARANCE = 50;
        const sortedFootprints = [...footprints].sort((a, b) => a - b);
        const medianFootprint = sortedFootprints[Math.floor(sortedFootprints.length / 2)];
        const halfChord = Math.sin(Math.PI / Math.max(count, 2));

        let ringSum = 0;
        for (let i = 0; i < count; i += 1) {
            const neighbour = (i + 1) % count;
            if (footprints[i] <= medianFootprint + 1e-6 && footprints[neighbour] <= medianFootprint + 1e-6) {
                ringSum = Math.max(ringSum, footprints[i] + footprints[neighbour] + 2 * GAP);
            }
        }
        const ringRadius = Math.max(MIN_HUB_DIST, ringSum / (2 * halfChord));
        const radii = footprints.map(() => ringRadius);
        const pushedOut = footprints.map((fp) => fp > medianFootprint + 1e-6);

        resolveCollisions({ radii, footprints, pushedOut, angleAt, clearance: PUSH_CLEARANCE });

        const bounds = { minX: -HUB_R, minY: -HUB_R, maxX: HUB_R, maxY: HUB_R };
        const grow = (x, y, rx, ry) => {
            bounds.minX = Math.min(bounds.minX, x - rx);
            bounds.maxX = Math.max(bounds.maxX, x + rx);
            bounds.minY = Math.min(bounds.minY, y - ry);
            bounds.maxY = Math.max(bounds.maxY, y + ry);
        };

        const layout = ordered.map((subnet, index) => {
            const angle = angleAt(index);
            const x = radii[index] * Math.cos(angle);
            const y = radii[index] * Math.sin(angle);
            grow(x, y, SUB_W / 2, SUB_H / 2);

            let next = 0;
            const machines = [];
            plans[index].forEach((ring, ringIndex) => {
                const step = (2 * Math.PI) / ring.count;
                for (let k = 0; k < ring.count; k += 1) {
                    const a = ring.count === 1
                        ? angle
                        : angle + (ringIndex * Math.PI) / ring.count + k * step;
                    const mx = x + ring.radius * Math.cos(a);
                    const my = y + ring.radius * Math.sin(a);
                    grow(mx, my, MACH_R, MACH_R);
                    machines.push({ pos: { x: mx, y: my }, machine: subnet.machines[next] });
                    next += 1;
                }
            });

            return { subnet, pos: { x, y }, machines };
        });

        const offsetX = -bounds.minX + PAD;
        const offsetY = -bounds.minY + PAD;
        const width = bounds.maxX - bounds.minX + PAD * 2;
        const height = bounds.maxY - bounds.minY + PAD * 2;

        const svg = svgEl('svg', {
            class: 'vlan-topo-svg',
            width,
            height,
            viewBox: `0 0 ${width} ${height}`,
        });

        const edges = svgEl('g', { class: 'topo-edges' });
        svg.appendChild(edges);

        const hubX = offsetX;
        const hubY = offsetY;

        layout.forEach((entry) => {
            const cx = entry.pos.x + offsetX;
            const cy = entry.pos.y + offsetY;
            edges.appendChild(svgEl('line', { class: 'topo-edge', x1: hubX, y1: hubY, x2: cx, y2: cy }));
            entry.machines.forEach((item) => {
                edges.appendChild(svgEl('line', {
                    class: 'topo-edge',
                    x1: cx,
                    y1: cy,
                    x2: item.pos.x + offsetX,
                    y2: item.pos.y + offsetY,
                }));
            });
        });

        layout.forEach((entry) => {
            entry.machines.forEach((item) => {
                const cx = item.pos.x + offsetX;
                const cy = item.pos.y + offsetY;
                const link = linkEl(item.machine.url, 'topo-machine');
                link.appendChild(svgEl('circle', { cx, cy, r: MACH_R }));

                const nameLines = wrapLines(item.machine.name, 11, 2);
                const ip = item.machine.ip || '';
                const description = String(item.machine.description || '').trim();
                const descLines = description ? wrapLines(description, 13, 2) : [];
                const sections = [{ lines: nameLines, lineHeight: 11, cls: 'topo-machine-label' }];
                if (ip) sections.push({ lines: [ip], lineHeight: 11, cls: 'topo-machine-ip' });
                if (descLines.length) {
                    sections.push({
                        lines: descLines,
                        lineHeight: 10,
                        cls: 'topo-machine-description',
                    });
                }

                const gap = 1;
                const totalHeight = sections.reduce(
                    (height, section, index) =>
                        height + section.lines.length * section.lineHeight + (index ? gap : 0),
                    0
                );
                let top = cy - totalHeight / 2;
                sections.forEach((section, index) => {
                    const sectionHeight = section.lines.length * section.lineHeight;
                    addText(link, section.cls, cx, top + sectionHeight / 2, section.lines, section.lineHeight);
                    top += sectionHeight + (index < sections.length - 1 ? gap : 0);
                });

                const title = svgEl('title');
                title.textContent = [
                    item.machine.ip,
                    item.machine.location,
                    description,
                ].filter(Boolean).join(' \u00b7 ');
                link.appendChild(title);
                svg.appendChild(link);
            });
        });

        layout.forEach((entry) => {
            const cx = entry.pos.x + offsetX;
            const cy = entry.pos.y + offsetY;
            const link = linkEl(entry.subnet.url, 'topo-subnet');
            link.appendChild(svgEl('rect', {
                x: cx - SUB_W / 2,
                y: cy - SUB_H / 2,
                width: SUB_W,
                height: SUB_H,
                rx: 8,
            }));
            addText(link, 'topo-subnet-name', cx, cy - 12, wrapLines(entry.subnet.name, 16, 3), 14);
            if (entry.subnet.prefix) {
                addText(link, 'topo-subnet-prefix', cx, cy + SUB_H / 2 - 14, wrapLines(entry.subnet.prefix, 26, 1), 11);
            }
            svg.appendChild(link);
        });

        const hub = svgEl('g', { class: 'topo-hub' });
        hub.appendChild(svgEl('circle', { cx: hubX, cy: hubY, r: HUB_R }));
        addText(hub, 'topo-hub-name', hubX, hubY - 6, wrapLines(data.center.name, 12, 2), 15);
        if (data.center.ip) {
            addText(hub, 'topo-hub-ip', hubX, hubY + 24, [data.center.ip], 11);
        }
        svg.appendChild(hub);

        stage.insertBefore(svg, stage.firstChild);
    }

    function applyTransform() {
        if (stage) stage.style.transform = `translate(${state.tx}px, ${state.ty}px) scale(${state.scale})`;
    }

    function fitToViewport() {
        if (!stage || !viewport) return;
        const stageWidth = stage.offsetWidth || 1;
        const stageHeight = stage.offsetHeight || 1;
        const viewWidth = viewport.clientWidth;
        const viewHeight = viewport.clientHeight;

        const fitScale = Math.min((viewWidth - 24) / stageWidth, (viewHeight - 24) / stageHeight);
        state.scale = clamp(fitScale, 0.03, 1);

        state.tx = (viewWidth - stageWidth * state.scale) / 2;
        state.ty = (viewHeight - stageHeight * state.scale) / 2;
        applyTransform();
    }

    function zoomAt(clientX, clientY, direction) {
        if (!viewport || !stage) return;
        const rect = viewport.getBoundingClientRect();
        const mouseX = clientX - rect.left;
        const mouseY = clientY - rect.top;
        const worldX = (mouseX - state.tx) / state.scale;
        const worldY = (mouseY - state.ty) / state.scale;
        const nextScale = clamp(state.scale * (direction > 0 ? 1.15 : 0.87), 0.02, 2.5);
        state.scale = nextScale;
        state.tx = mouseX - worldX * nextScale;
        state.ty = mouseY - worldY * nextScale;
        applyTransform();
    }

    controls.forEach((button) => {
        button.addEventListener('click', () => {
            const cx = viewport.clientWidth / 2;
            const cy = viewport.clientHeight / 2;
            const action = button.dataset.zoom;
            if (action === 'in') zoomAt(cx, cy, 1);
            if (action === 'out') zoomAt(cx, cy, -1);
            if (action === 'reset') fitToViewport();
        });
    });

    if (viewport) {
        viewport.addEventListener('pointerdown', (event) => {
            if (event.button !== 0) return;
            if (event.target.closest('a, button')) return;
            state.dragging = true;
            state.dragStartX = event.clientX;
            state.dragStartY = event.clientY;
            state.startTx = state.tx;
            state.startTy = state.ty;
            viewport.setPointerCapture(event.pointerId);
        });

        viewport.addEventListener('pointermove', (event) => {
            if (!state.dragging) return;
            state.tx = state.startTx + (event.clientX - state.dragStartX);
            state.ty = state.startTy + (event.clientY - state.dragStartY);
            applyTransform();
        });

        viewport.addEventListener('pointerup', (event) => {
            state.dragging = false;
            if (viewport.hasPointerCapture(event.pointerId)) viewport.releasePointerCapture(event.pointerId);
        });

        viewport.addEventListener('pointerleave', () => { state.dragging = false; });

        viewport.addEventListener('wheel', (event) => {
            if (event.target.closest('a, button')) return;
            event.preventDefault();
            zoomAt(event.clientX, event.clientY, event.deltaY < 0 ? 1 : -1);
        }, { passive: false });
    }

    const exportButton = document.querySelector('[data-export-svg]');

    async function svgStyles() {
        // Inline the plugin stylesheet so the downloaded file renders styled;
        // falls back to unstyled if the fetch fails.
        const link = document.querySelector('link[href*="vlan_topology.css"]');
        try {
            let css = await fetch(link.href).then((response) => response.text());
            css = css.replace(/[^{}]*:hover[^{}]*\{[^}]*\}/g, '');
            return `${css}\n.topo-export-bg { fill: #fff; }`;
        } catch (error) {
            return '.topo-export-bg { fill: #fff; }';
        }
    }

    async function exportSvg() {
        const svg = stage ? stage.querySelector('svg.vlan-topo-svg') : null;
        if (!svg) return;
        const clone = svg.cloneNode(true);
        clone.setAttribute('xmlns', SVG_NS);
        // Static export: unwrap links into plain groups (keeping their
        // classes for the fills/strokes) and drop hover tooltips.
        clone.querySelectorAll('a').forEach((anchor) => {
            const group = svgEl('g', { class: anchor.getAttribute('class') });
            while (anchor.firstChild) group.appendChild(anchor.firstChild);
            anchor.replaceWith(group);
        });
        clone.querySelectorAll('title').forEach((title) => title.remove());
        clone.insertBefore(svgEl('style'), clone.firstChild).textContent = await svgStyles();
        clone.insertBefore(
            svgEl('rect', {
                class: 'topo-export-bg',
                x: 0,
                y: 0,
                width: svg.getAttribute('width'),
                height: svg.getAttribute('height'),
            }),
            clone.firstChild.nextSibling
        );
        const source = `<?xml version="1.0" encoding="UTF-8"?>\n${new XMLSerializer().serializeToString(clone)}`;
        const url = URL.createObjectURL(new Blob([source], { type: 'image/svg+xml;charset=utf-8' }));
        const anchor = document.createElement('a');
        anchor.href = url;
        anchor.download = `vlan_topology_${new Date().toISOString().slice(0, 10)}.svg`;
        anchor.click();
        URL.revokeObjectURL(url);
    }

    if (exportButton) exportButton.addEventListener('click', exportSvg);

    buildGraph();
    fitToViewport();
    window.addEventListener('resize', fitToViewport);
    window.addEventListener('load', fitToViewport);
})();
