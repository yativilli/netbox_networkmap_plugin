(function () {
    const dataNode = document.getElementById('subnet-map-data');
    if (!dataNode || typeof L === 'undefined') {
        return;
    }
    const mapData = JSON.parse(dataNode.textContent);
    const UI = mapData.ui || {};
    const t = (key, fallback) => UI[key] || fallback;

    const SWISSSTOPO_URL =
        'https://wmts.geo.admin.ch/1.0.0/ch.swisstopo.pixelkarte-farbe/default/current/21781/{z}/{y}/{x}.jpeg';
    const EMPTY_TILE = 'data:image/gif;base64,R0lGODlhAQABAAAAACH5BAEKAAEALAAAAAABAAEAAAICTAEAOw=';
    // Switzerland plus a margin; also keeps the view inside the
    // area covered by the LV03 tile grid.
    const COVERAGE_BOUNDS = L.latLngBounds([[45.82, 6.0], [47.9, 10.75]]);

    // swisstopo LV03 (EPSG:21781) tile grid: origin 420000/350000,
    // resolution 4000 - 250 * z m/px for z <= 13, then per the
    // official WMTSCapabilities down to 0.1.
    const LV03_RESOLUTIONS = (() => {
        const resolutions = [];
        for (let z = 0; z <= 13; z++) {
            resolutions.push(4000 - 250 * z);
        }
        [650, 500, 250, 100, 50, 20, 10, 5, 2.5, 2, 1.5, 1,
            0.5, 0.25, 0.1, 0.05, 0.025].forEach((res) => resolutions.push(res));
        return resolutions;
    })();

    // LV03 CRS fed by the precomputed projection grid (lv03_grid.js,
    // generated from the official EPSG:4326 -> EPSG:21781 operation),
    // which reproduces the swisstopo tile grid; the legacy +towgs84
    // proj4 string used previously drifts by up to tens of km.
    const LV03_CRS = L.extend({}, L.CRS, {
        code: 'EPSG:21781',
        projection: {
            project: (latlng) => {
                const p = window.LV03.project(latlng.lat, latlng.lng);
                return L.point(p.e, p.n);
            },
            unproject: (point) => {
                const ll = window.LV03.unproject(point.x, point.y);
                return L.latLng(ll.lat, ll.lng);
            },
            bounds: L.latLngBounds([[-85, -180], [85, 180]])
        },
        transformation: L.transformation(1, -420000, -1, 350000),
        scale: (zoom) => {
            const z = Math.min(Math.max(Math.round(zoom), 0), LV03_RESOLUTIONS.length - 1);
            return 1 / LV03_RESOLUTIONS[z];
        },
        zoom: (scale) => {
            const res = 1 / scale;
            for (let z = 0; z < LV03_RESOLUTIONS.length - 1; z++) {
                if (res >= LV03_RESOLUTIONS[z + 1]) {
                    const a = LV03_RESOLUTIONS[z];
                    const b = LV03_RESOLUTIONS[z + 1];
                    return z + (a - res) / (a - b);
                }
            }
            return LV03_RESOLUTIONS.length - 1;
        },
        distance: L.CRS.Earth.distance,
        R: 6371000,
        infinite: true
    });

    const pins = mapData.pins || [];
    const groups = {};
    pins.forEach((pin) => {
        const key = pin.lat.toFixed(4) + ',' + pin.lon.toFixed(4);
        if (!groups[key]) {
            groups[key] = {site: pin.site, lat: pin.lat, lon: pin.lon, pins: []};
        }
        groups[key].pins.push(pin);
    });

    // House mode: deep zoom onto a site swaps the map for the
    // building's floor plan and scatters that site's machines on it.
    const siteLocations = mapData.locations || {};
    const layoutCache = {};
    const HOUSE_ENTER_ZOOM = 24;
    const HOUSE_EXIT_ZOOM = 23;
    const HOUSE_ENTER_M = 150;
    const HOUSE_LEAVE_M = 400;
    // Slot grid (fractional x/y) for uploaded custom plans, which have
    // no server-side layout.
    const CUSTOM_SLOTS = [];
    [0.3, 0.5, 0.7].forEach((fy) => {
        [0.2, 0.4, 0.6, 0.8].forEach((fx) => CUSTOM_SLOTS.push([fx, fy]));
    });
    const house = {
        activeKey: null,
        group: null,
        marker: null,
        layer: null,
        planOverlay: null,
        machines: null,
        badge: null
    };
    const PIN_W = 22;
    const PIN_H = 31;
    const CLUSTER_W = 30;
    const CLUSTER_H = 42;
    const PIN_PATH = 'M15 0C6.7 0 0 6.7 0 15c0 10.9 15 27 15 27s15-16.1 15-27C30 6.7 23.3 0 15 0z';

    const panel = document.getElementById('subnet-detail-panel');
    const panelTitle = document.getElementById('subnet-detail-title');
    const panelBody = document.getElementById('subnet-detail-body');

    function closePanel() {
        if (panel.classList.contains('is-open')) {
            panel.classList.remove('is-open');
            if (window.__subnetMap) {
                window.__subnetMap.invalidateSize();
            }
        }
    }
    document.getElementById('subnet-detail-close').addEventListener('click', closePanel);

    const labelsToggle = document.getElementById('subnet-labels-toggle');
    const mapContainer = document.getElementById('subnet-map');
    if (labelsToggle && mapContainer) {
        labelsToggle.addEventListener('click', () => {
            const hidden = mapContainer.classList.toggle('labels-hidden');
            labelsToggle.setAttribute('aria-pressed', hidden ? 'true' : 'false');
            labelsToggle.textContent = hidden ? t('labels_show', 'Show labels') : t('labels_hide', 'Hide labels');
        });
    }

    // The regional map is exported as a raster picture, a building's floor
    // plan as a scalable drawing that stays sharp when printed large.
    function setExportCaption(inHouse) {
        const exportButton = document.querySelector('[data-export-svg]');
        if (exportButton) {
            exportButton.textContent = inHouse
                ? t('export_svg', 'Export as .SVG')
                : t('export_png', 'Export as .PNG');
        }
    }

    function openPanel() {
        panel.classList.add('is-open');
        if (window.__subnetMap) {
            window.__subnetMap.invalidateSize();
        }
    }

    function escapeHtml(text) {
        const entities = {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'};
        return String(text).replace(/[&<>"]/g, (ch) => entities[ch]);
    }

    function el(tag, cssClass, text) {
        const node = document.createElement(tag);
        if (cssClass) {
            node.className = cssClass;
        }
        if (text !== undefined && text !== null) {
            node.textContent = text;
        }
        return node;
    }

    function linkHtml(url, text, cssClass) {
        const cls = cssClass ? ` class="${cssClass}"` : '';
        if (url) {
            return `<a href="${escapeHtml(url)}"${cls} target="_blank" rel="noopener">${text}</a>`;
        }
        return `<span${cls}>${text}</span>`;
    }

    const ipCmp = (a, b) => a.ip.localeCompare(b.ip, undefined, {numeric: true});

    // Flatten one site group's machines into one list, ordered by IP
    // like the dots on the floor plan. Panel lists and house-mode
    // markers share it so the two always show the same set and order.
    function collectMachines(group) {
        const machines = [];
        group.pins.forEach((pin) => {
            pin.machines.forEach((machine) => machines.push({
                name: machine.name, ip: machine.ip,
                description: machine.description || '',
                url: machine.url, color: pin.color,
                room: machine.room || '',
                physical: machine.physical !== false
            }));
        });
        machines.sort(ipCmp);
        return machines;
    }

    function machineListHtml(machines) {
        if (!machines.length) {
            return `<div class="detail-empty">${t('no_machines', 'No machines')}</div>`;
        }
        // Virtual machines are flagged like on the floor plan.
        const items = machines.slice().sort(ipCmp).map((machine) =>
            `<li${machine.physical ? '' : ' class="is-vm"'}>` +
            `${linkHtml(machine.url, escapeHtml(machine.name))}` +
            `<span class="detail-ip"> \u2013 ${escapeHtml(machine.ip)}</span>` +
            `${machine.physical ? '' : '<span class="detail-machine-vm">' + t('vm', 'VM') + '</span>'}</li>`).join('');
        return `<ul class="detail-machines">${items}</ul>`;
    }

    function renderPanel(title, bodyHtml) {
        panelTitle.textContent = title;
        panelBody.innerHTML = bodyHtml;
        openPanel();
    }

    function showVlanPanel(pin) {
        const word = pin.machines.length === 1 ? t('machine', 'machine') : t('machines', 'machines');
        renderPanel(pin.subnet, `
            <div class="detail-prefix">${linkHtml(pin.url, escapeHtml(pin.prefix || pin.subnet))}</div>
            <div class="detail-site">${escapeHtml(pin.site)}</div>
            <details class="detail-section" open>
                <summary>${pin.machines.length} ${word}</summary>
                ${machineListHtml(pin.machines)}
            </details>`);
    }

    function showAddressPanel(group) {
        const word = group.pins.length === 1 ? t('subnet', 'subnet') : t('subnets', 'subnets');
        const sections = group.pins.slice().sort((a, b) => a.prefix.localeCompare(b.prefix)).map((pin) => `
            <details class="detail-section detail-vlan">
                <summary><span class="detail-dot" style="background:${pin.color}"></span>` +
            `<span class="detail-vlan-name">${escapeHtml(pin.prefix || pin.subnet)}</span>` +
            `<span class="detail-count">${pin.machines.length}</span></summary>
                <div class="detail-vlan-head">
                    ${pin.subnet !== pin.prefix ? `<div class="detail-vlan-subnet">${escapeHtml(pin.subnet)}</div>` : ''}
                    ${linkHtml(pin.url, escapeHtml(pin.prefix || pin.subnet), 'detail-vlan-link')}
                </div>
                ${machineListHtml(pin.machines)}
            </details>`).join('');
        renderPanel(group.site, `<div class="detail-site">${group.pins.length} ${word}</div>${sections}`);
    }

    const pinSvg = (color) =>
        `<svg width="22" height="31" viewBox="0 0 30 42" aria-hidden="true">` +
        `<path d="${PIN_PATH}" fill="${color}" stroke="#ffffff" stroke-width="1.8"/>` +
        '<circle cx="15" cy="15" r="5.5" fill="#ffffff"/></svg>';

    const clusterSvg = (count) =>
        '<div class="subnet-cluster-pin">' +
        `<svg width="30" height="42" viewBox="0 0 30 42" aria-hidden="true">` +
        `<path d="${PIN_PATH}" fill="#ffffff" stroke="#343a40" stroke-width="2"/></svg>` +
        `<span class="subnet-cluster-count">${count}</span></div>`;

    function bindPinLabel(marker, site, pin, extraClass) {
        marker.bindTooltip(
            `<span class="pin-label-site">${site}</span>` +
            `<span class="pin-label-subnet">${pin.subnet}` +
            `${pin.prefix && pin.prefix !== pin.subnet ? ` &middot; ${pin.prefix}` : ''}</span>`,
            {
                permanent: true,
                direction: 'bottom',
                offset: [0, 6],
                className: 'subnet-pin-label' + (extraClass || '')
            });
    }

    function clearObj(obj) {
        Object.keys(obj).forEach((key) => delete obj[key]);
    }

    function resetHouseState() {
        house.activeKey = null;
        house.group = null;
        house.marker = null;
        house.layer = null;
        house.planOverlay = null;
        house.machines = null;
        if (house.badge) {
            house.badge.remove();
            house.badge = null;
        }
        window.__subnetMapHouse = null;
    }

    const CANTON_HALO_STYLE = {
        stroke: true, color: '#ffffff', weight: 8, opacity: 0.4, fill: false
    };
    const CANTON_BORDER_STYLE = {
        stroke: true, color: '#c8102e', weight: 3, opacity: 0.95,
        dashArray: '8 6', fill: true, fillColor: '#c8102e', fillOpacity: 0.10
    };
    let cantonBoundary = null;
    let cantonLayers = [];

    function addCantonBorder(map) {
        if (!cantonBoundary) {
            return;
        }
        const renderer = L.canvas({padding: 0.2});
        cantonLayers = [CANTON_HALO_STYLE, CANTON_BORDER_STYLE].map((style) => L.geoJSON(cantonBoundary, {
            renderer: renderer,
            interactive: false,
            style: style
        }).addTo(map));
    }

    const expanded = {};
    const grids = {};
    const clusterMarkers = {};
    const singleMarkers = {};

    function renderGroupPins(group, container) {
        const count = group.pins.length;
        const cols = Math.min(8, Math.max(3, Math.round(Math.sqrt(count) * 1.4)));
        const last = count - 1;
        const lastPos = last % cols;
        const lastRow = Math.floor(last / cols);
        const centerX = (14 * lastPos + 7 * lastRow) / 2;
        const centerY = (20 * lastRow - 9 * lastPos) / 2;

        group.pins.forEach((pin, index) => {
            const pos = index % cols;
            const row = Math.floor(index / cols);
            const dx = Math.round(14 * pos + 7 * row - centerX);
            const dy = Math.round(20 * row - 9 * pos - centerY);

            const icon = L.divIcon({
                className: 'subnet-pin-icon',
                html: `<div class="subnet-pin" style="transform: translate(${dx}px,${dy}px);">` +
                    `${pinSvg(pin.color)}</div>`,
                iconSize: [PIN_W, PIN_H],
                iconAnchor: [PIN_W / 2, PIN_H]
            });

            const marker = L.marker([pin.lat, pin.lon], {
                icon: icon,
                zIndexOffset: 4000 + count * 100 - index * 10
            });
            marker.on('click', () => showVlanPanel(pin));
            bindPinLabel(marker, group.site, pin, ' subnet-grid-label');
            marker.addTo(container);
        });
    }

    function collapseGroup(map, key) {
        if (!expanded[key]) {
            return;
        }
        map.removeLayer(grids[key]);
        delete grids[key];
        delete expanded[key];
    }

    function collapseAll(map, exceptKey) {
        Object.keys(expanded).forEach((key) => {
            if (key !== exceptKey) {
                collapseGroup(map, key);
            }
        });
    }

    function toggleGroup(map, key, group) {
        const wasExpanded = !!expanded[key];
        collapseAll(map, key);
        if (wasExpanded) {
            collapseGroup(map, key);
            closePanel();
        } else {
            expanded[key] = true;
            const grid = L.layerGroup();
            renderGroupPins(group, grid);
            grid.addTo(map);
            grids[key] = grid;
            showAddressPanel(group);
        }
    }

    function buildPins(map) {
        Object.keys(groups).forEach((key) => {
            const group = groups[key];

            if (group.pins.length === 1) {
                const pin = group.pins[0];
                const marker = L.marker([pin.lat, pin.lon], {
                    icon: L.divIcon({
                        className: 'subnet-pin-icon',
                        html: `<div class="subnet-pin">${pinSvg(pin.color)}</div>`,
                        iconSize: [PIN_W, PIN_H],
                        iconAnchor: [PIN_W / 2, PIN_H]
                    }),
                    zIndexOffset: 5000
                });
                marker.on('click', () => showVlanPanel(pin));
                bindPinLabel(marker, pin.site, pin);
                marker.addTo(map);
                singleMarkers[key] = marker;
                return;
            }

            const marker = L.marker([group.lat, group.lon], {
                icon: L.divIcon({
                    className: 'subnet-pin-icon subnet-cluster-icon',
                    html: clusterSvg(group.pins.length),
                    iconSize: [CLUSTER_W, CLUSTER_H],
                    iconAnchor: [CLUSTER_W / 2, CLUSTER_H]
                }),
                zIndexOffset: 2000
            }).addTo(map);
            clusterMarkers[key] = marker;
            marker.bindTooltip(
                `<span class="cluster-label-site">${group.site}</span>` +
                `<span class="cluster-label-details">${group.pins.length} ` +
                `${t('subnets', 'subnets')} \u00b7 ${t('details', 'Details')}</span>`,
                {permanent: true, direction: 'top', offset: [0, -44],
                    className: 'subnet-cluster-tooltip'});
            marker.on('click', () => toggleGroup(map, key, group));
        });
    }

    function housePlanOf(group) {
        const withPlan = group.pins.find((pin) => pin.plan_url);
        if (withPlan) {
            return {
                url: withPlan.plan_url,
                w: withPlan.plan_w || 1200,
                h: withPlan.plan_h || 850,
                custom: true
            };
        }
        return {logical: true, url: '', w: 1400, h: 850, custom: false};
    }

    function houseFootprint(plan) {
        // The default footprint is ~120 m x 85 m of ground area;
        // uploaded plans keep it, adjusted to their aspect ratio.
        // Logical maps grow with the number of floors so each stays
        // readable.
        let area = 120 * 85;
        if (plan.logical) {
            area = Math.min(20400, Math.max(10200, 10200 * plan.h / 850));
        }
        const ratio = plan.w / plan.h;
        return {w: Math.sqrt(area * ratio), h: Math.sqrt(area / ratio)};
    }

    function houseBounds(lat, lon, width, height) {
        const dLat = height / 2 / 111320;
        const dLon = width / 2 / (111320 * Math.cos(lat * Math.PI / 180));
        return L.latLngBounds([[lat - dLat, lon - dLon], [lat + dLat, lon + dLon]]);
    }

    // Fractional position on the plan -> coordinates, interpolated
    // in projected space so it holds in any CRS.
    function slotToLatLng(bounds, fx, fy) {
        const zoom = 27;
        const nw = currentMap.project(bounds.getNorthWest(), zoom);
        const se = currentMap.project(bounds.getSouthEast(), zoom);
        return currentMap.unproject(
            L.point(nw.x + fx * (se.x - nw.x), nw.y + fy * (se.y - nw.y)), zoom);
    }

    function ipHash(text) {
        let hash = 0;
        for (let i = 0; i < text.length; i++) {
            hash = (hash * 31 + text.charCodeAt(i)) | 0;
        }
        return Math.abs(hash);
    }

    // Derive a floor from a NetBox location name, e.g.
    // "2. Stock - Gang - DigiKri" -> 2. Stock, "U204" -> UG,
    // "O 242" -> OG (attic), "Büro 267" -> 2. Stock, "019" -> EG.
    // The German labels (UG/EG/OG, "N. Stock") are the Swiss
    // building convention and deliberately stay untranslated.
    function logicalFloor(name) {
        let m = name.match(/(\d+)\.\s*stock\b/i);
        if (m) {
            const n = parseInt(m[1], 10);
            return {sort: n, label: `${n}. Stock`};
        }
        if (/^(UG|ET|KG)\b/i.test(name) || /^U[\d\s]/.test(name)) {
            return {sort: -2, label: 'UG'};
        }
        if (/^EG\b/i.test(name)) {
            return {sort: 0, label: 'EG'};
        }
        if (/^(OG|AD)\b/i.test(name) || /^O[\d\s]/.test(name)) {
            return {sort: 100, label: 'OG'};
        }
        m = name.match(/\b(\d{2,3})\b/);
        if (m) {
            const d = parseInt(m[1].charAt(0), 10);
            return d === 0 ? {sort: 0, label: 'EG'} : {sort: d, label: `${d}. Stock`};
        }
        return {sort: 200, label: t('other_rooms', 'Other rooms')};
    }

    // Calibrated font/geometry metrics; they keep room labels and
    // count chips from ever overlapping and were tuned against
    // real floor-plan renderings.
    const CHIP_CHAR_W = 7.4;         // glyph width of the 14px count chip
    const ROOM_LABEL_CHAR_W = 8.6;   // glyph width of the 17px room label
    const FLOOR_LABEL_CHAR_W = 11.7; // glyph width of the 22px floor label
    const GRID_PAD = 16;             // padding inside a room box's dot grid
    const GRID_DOT_DX = 18;          // minimum horizontal dot spacing
    const GRID_DOT_DENSITY = 2.5;    // target fill ratio of the dot grid
    const GRID_ROW_H = 30;           // machine-dot row pitch
    const ROOM_MIN_H = 150;          // minimum room box height

    const FLOOR_LINE_H = 24;          // pitch of a wrapped floor name's lines

    // Words of a label placed on as many lines as the given width takes. Only
    // a word wider than the line itself is broken, so nothing of a name is
    // lost the way a cut-off one is.
    function wrapWords(value, widthPx, charW) {
        const take = Math.max(1, Math.floor(widthPx / charW));
        const words = [];
        String(value).split(/\s+/).filter(Boolean).forEach((word) => {
            for (let i = 0; i < word.length; i += take) words.push(word.slice(i, i + take));
        });
        const lines = [];
        let line = '';
        words.forEach((word) => {
            const joined = line ? `${line} ${word}` : word;
            if (line && joined.length * charW > widthPx) {
                lines.push(line);
                line = word;
            } else {
                line = joined;
            }
        });
        if (line) lines.push(line);
        return lines.length ? lines : [String(value)];
    }

    function clipRoomLabel(name, widthPx) {
        const max = Math.max(6, Math.floor((widthPx - 10) / ROOM_LABEL_CHAR_W));
        return name.length > max
            ? name.slice(0, Math.max(1, max - 1)) + '\u2026'
            : name;
    }

    // Columns a room box of the given width fits for `count`
    // machines: enough that dots fill the box without touching.
    function roomGridCols(widthPx, count) {
        return Math.max(1, Math.min(
            Math.floor((widthPx - GRID_PAD) / GRID_DOT_DX),
            Math.ceil(Math.sqrt(count * GRID_DOT_DENSITY))));
    }

    // Logical building map generated from NetBox locations: rooms
    // are Location objects, floors are parsed from their names and
    // drawn as bands (top floor first); empty rooms are shown too.
    // Sites without any rooms get a single machine band instead.
    function buildLogicalLayout(group) {
        const counts = {};
        let vmTotal = 0;
        for (const pin of group.pins) {
            for (const machine of pin.machines) {
                if (machine.physical === false) {
                    vmTotal += 1;
                    continue;
                }
                const room = machine.room || '';
                counts[room] = (counts[room] || 0) + 1;
            }
        }
        const rooms = Object.keys(counts);
        for (const name of siteLocations[group.site] || []) {
            if (!rooms.includes(name)) {
                rooms.push(name);
            }
            if (!(name in counts)) {
                counts[name] = 0;
            }
        }

        const bySort = new Map();
        for (const name of rooms) {
            if (name === '') {
                continue;
            }
            const f = logicalFloor(name);
            if (!bySort.has(f.sort)) {
                bySort.set(f.sort, {sort: f.sort, label: f.label, rooms: []});
            }
            bySort.get(f.sort).rooms.push(name);
        }
        const floors = [...bySort.values()].sort((a, b) => b.sort - a.sort);

        if (rooms.includes('')) {
            const single = rooms.every((name) => name === '');
            floors.push({
                sort: -1000,
                label: single
                    ? t('machines_band', 'Machines')
                    : t('no_location', 'No location'),
                rooms: ['']
            });
        }
        if (vmTotal > 0) {
            counts['__virtual__'] = vmTotal;
            floors.push({sort: -2000, label: t('virtual', 'Virtual'),
                rooms: ['__virtual__']});
        }

        const W = 1400, PAD = 34, GAP = 14;
        const BAND_MIN = 150;   // the floor name's column is never narrower
        const BAND_MAX = 300;   // nor wider; a longer name goes over lines
        // The column keeps room for the longest floor name on one line, so a
        // name such as "Other rooms" is not cut to what the column was.
        const widestFloor = floors.reduce(
            (wide, floor) => Math.max(wide, String(floor.label).length), 0);
        const BAND_W = Math.min(
            BAND_MAX, Math.max(BAND_MIN, Math.ceil(widestFloor * FLOOR_LABEL_CHAR_W) + 24));

        // Pre-plan each floor band: room widths go by machine
        // count and the band grows tall enough that the machine
        // grids never collapse onto each other.
        const bands = floors.map((floor) => {
            const gap = floor.rooms.length > 1 ? 10 : 0;
            const availW = W - 2 * PAD - BAND_W - 12 - gap * (floor.rooms.length - 1);
            const weights = floor.rooms.map(
                (name) => Math.pow(counts[name] || 0, 0.65) + 1.6);
            const totalW = weights.reduce((a, b) => a + b, 0);
            let maxRows = 1;
            let stacked = false;
            const widths = floor.rooms.map((name, i) => {
                const w = Math.max(60, availW * weights[i] / totalW);
                const count = counts[name] || 0;
                const cols = roomGridCols(w, count);
                maxRows = Math.max(maxRows, Math.ceil(count / cols));
                if (name !== '' && name !== '__virtual__' &&
                        count > 0 &&
                        w - countChipWidth(name, count) - 12 < 60) {
                    stacked = true;
                }
                return {w, cols};
            });
            const boxH = Math.max(ROOM_MIN_H, maxRows * GRID_ROW_H + 24);
            return {floor, gap, widths, boxH, stacked, shift: stacked ? 24 : 0};
        });
        const H = 110 +
            bands.reduce((a, band) => a + band.boxH + 90 + GAP + band.shift, 0) +
            PAD;

        const boxes = {};
        const svg = [
            `<rect x="0" y="0" width="${W}" height="${H}" fill="#f8f5ec"/>`,
            `<rect x="4" y="4" width="${W - 8}" height="${H - 8}" ` +
            'fill="none" stroke="#555" stroke-width="4"/>',
            `<text x="${PAD}" y="64" font-size="26" fill="#3d3d38"` +
            ` font-style="italic">${escapeHtml(group.site)} \u2014 ` +
            `${escapeHtml(t('logical_title', 'logical floor map'))}</text>`,
            `<text x="${W - PAD}" y="64" text-anchor="end"` +
            ` font-size="16" fill="#8a8378">` +
            `${escapeHtml(t('generated_from', 'generated from NetBox locations'))}` +
            '</text>'
        ];

        let y0 = 110;
        for (const band of bands) {
            const {floor, gap, widths, boxH, stacked, shift} = band;
            svg.push(`<rect x="${PAD}" y="${y0}" width="${W - 2 * PAD}" ` +
                `height="${boxH + 74 + shift}" rx="8" fill="#ece7da" ` +
                'stroke="#d8d2c2" stroke-width="1.5"/>');
            // The name is written whole, in the column it was given and in as
            // many lines as that column takes.
            wrapWords(floor.label, BAND_W - 16, FLOOR_LABEL_CHAR_W).forEach(
                (line, k) => {
                    svg.push(`<text x="${PAD + BAND_W / 2}" ` +
                        `y="${y0 + 40 + k * FLOOR_LINE_H}" text-anchor="middle" ` +
                        'font-size="22" font-weight="bold" fill="#6b5d4a">' +
                        `${escapeHtml(line)}</text>`);
                });
            const boxTop = y0 + 62 + shift;
            let x = PAD + BAND_W + 6;
            floor.rooms.forEach((name, i) => {
                const w = widths[i].w;
                const count = counts[name] || 0;
                const chip = count > 0 ? countChipText(name, count) : '';
                if (name !== '' && name !== '__virtual__') {
                    // Narrow boxes stack name over count instead
                    // of letting them run into each other.
                    const budget = stacked ? w - 6
                        : w - (count > 0 ? countChipWidth(name, count) + 12 : 10);
                    svg.push(`<text x="${x}" ` +
                        `y="${boxTop - (stacked ? 32 : 8)}" ` +
                        'font-size="17" fill="#3d3d38">' +
                        `${escapeHtml(clipRoomLabel(name, budget))}</text>`);
                }
                if (count > 0) {
                    svg.push('<text ' +
                        (stacked ? `x="${x}"` : `x="${x + w - 6}" text-anchor="end"`) +
                        ` y="${boxTop - 8}" font-size="14" fill="#8a8378">` +
                        `${escapeHtml(chip)}</text>`);
                }
                svg.push(`<rect x="${x}" y="${boxTop}" width="${w}" ` +
                    `height="${boxH}" rx="6" fill="#f7f4ea" ` +
                    'stroke="#6b6b63" stroke-width="2.5"/>');
                boxes[name] = {x, y: boxTop, w, h: boxH, cols: widths[i].cols};
                x += w + gap;
            });
            y0 += boxH + 90 + GAP + shift;
        }
        return {w: W, h: H, boxes, markup: svg.join('')};
    }

    function countChipText(name, count) {
        if (name === '__virtual__') {
            return count + (count === 1 ? ' ' + t('vm', 'VM') : ' ' + t('vms', 'VMs'));
        }
        return count + (count === 1 ? ' ' + t('machine', 'machine') : ' ' + t('machines', 'machines'));
    }

    // Rough rendered width of the 14px count chip.
    function countChipWidth(name, count) {
        return countChipText(name, count).length * CHIP_CHAR_W + 4;
    }

    // The floor plan as a hand-rolled SVG overlay: Firefox drops
    // raster content (img, canvas, background) inside the deeply
    // translated map panes at house zoom, but paints vectors
    // reliably, so the plan is inlined into an <svg> sized to the
    // footprint on every view change.
    function createPlanOverlay(plan, bounds) {
        const node = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        node.setAttribute('class', 'house-plan-overlay');
        node.setAttribute('viewBox', `0 0 ${plan.w} ${plan.h}`);
        node.setAttribute('preserveAspectRatio', 'xMidYMid meet');
        node.style.position = 'absolute';

        function reset() {
            if (!currentMap) {
                return;
            }
            const nw = currentMap.latLngToLayerPoint(bounds.getNorthWest());
            const se = currentMap.latLngToLayerPoint(bounds.getSouthEast());
            node.style.width = Math.max(1, Math.round(se.x - nw.x)) + 'px';
            node.style.height = Math.max(1, Math.round(se.y - nw.y)) + 'px';
            L.DomUtil.setPosition(node, nw);
        }

        function attach(map) {
            map.getPanes().overlayPane.appendChild(node);
            map.on('zoomend moveend viewreset', reset);
            reset();
            if (plan.markup) {
                node.innerHTML = plan.markup;
            } else if (/\.svg(\?|$)/i.test(plan.url)) {
                fetch(plan.url)
                    .then((response) => (response.ok ? response.text() : ''))
                    .then((text) => {
                        const root = new DOMParser()
                            .parseFromString(text, 'image/svg+xml')
                            .querySelector('svg');
                        if (!root) {
                            return;
                        }
                        root.setAttribute('width', '100%');
                        root.setAttribute('height', '100%');
                        node.appendChild(document.importNode(root, true));
                    })
                    .catch(() => {});
            } else {
                const raster = document.createElementNS('http://www.w3.org/2000/svg', 'image');
                raster.setAttribute('href', plan.url);
                raster.setAttribute('width', plan.w);
                raster.setAttribute('height', plan.h);
                node.appendChild(raster);
            }
        }

        function detach(map) {
            map.off('zoomend moveend viewreset', reset);
            if (node.parentNode) {
                node.parentNode.removeChild(node);
            }
        }

        return {attach: attach, detach: detach};
    }

    function addMachineMarkers(group, bounds, plan) {
        const layer = L.layerGroup();
        const machines = collectMachines(group);

        // Physical machines go into their room's box grid, virtual
        // ones into the server-built "Virtual" band.
        const gridRoom = (machine) => (machine.physical ? machine.room : '__virtual__');
        const layout = plan.layout || null;
        const roomTotals = {};
        if (layout) {
            machines.forEach((machine) => {
                const room = gridRoom(machine);
                roomTotals[room] = (roomTotals[room] || 0) + 1;
            });
        }
        const roomSeen = {};

        machines.forEach((machine, index) => {
            let fx;
            let fy;
            if (layout) {
                const room = gridRoom(machine);
                const box = layout.boxes[room] || layout.boxes[''] ||
                    {x: 40, y: layout.h / 2, w: layout.w - 80, h: 60};
                const k = roomSeen[room] = roomSeen[room] || 0;
                roomSeen[room] = k + 1;
                const total = roomTotals[room];
                const cols = box.cols || roomGridCols(box.w, total);
                const rows = Math.max(1, Math.ceil(total / cols));
                const cellW = (box.w - GRID_PAD) / cols;
                const cellH = Math.max(GRID_PAD, (box.h - GRID_PAD) / rows);
                fx = (box.x + 8 + ((k % cols) + 0.5) * cellW) / layout.w;
                fy = (box.y + 8 + Math.floor(k / cols) * cellH + cellH / 2) / layout.h;
            } else {
                const slot = CUSTOM_SLOTS[index % CUSTOM_SLOTS.length];
                const round = Math.floor(index / CUSTOM_SLOTS.length);
                const hash = ipHash(machine.ip) + round * 17;
                fx = slot[0] + (round === 0 ? 0 : ((hash % 7) - 3) * 0.012);
                fy = slot[1] + (round === 0 ? 0 : (((hash >> 3) % 7) - 3) * 0.02);
            }
            const style = machine.physical
                ? `background:${machine.color}`
                : `background:#fff;border-color:${machine.color}`;
            const at = slotToLatLng(bounds, fx, fy);
            // The SVG export draws permanent name/IP labels for these dots;
            // on screen the same data is only a hover tooltip, which has room
            // for one more line: what the machine is for.
            machine.lat = at.lat;
            machine.lng = at.lng;
            const marker = L.marker(at, {
                icon: L.divIcon({
                    className: 'subnet-machine-icon',
                    html: `<div class="subnet-machine-pin` +
                        `${machine.physical ? '' : ' virtual'}" style="${style}"></div>`,
                    iconSize: [14, 14],
                    iconAnchor: [7, 7]
                }),
                zIndexOffset: 6000 + index
            });
            // A device without a DNS name is named by its address, and the
            // description - what it is or does - is said underneath unless it
            // would only repeat that name.
            const named = machine.name || machine.ip;
            const purpose = machine.description && machine.description !== named
                ? `<span class="machine-desc">${escapeHtml(machine.description)}</span>`
                : '';
            marker.bindTooltip(
                `<span class="machine-name">${escapeHtml(named)}</span>` +
                `<span class="machine-ip">${escapeHtml(machine.ip)}</span>` +
                purpose,
                {direction: 'top', offset: [0, -8], className: 'subnet-machine-tooltip'});
            if (machine.url) {
                marker.on('click', () => window.open(machine.url, '_blank', 'noopener'));
            }
            marker.addTo(layer);
        });
        layer.addTo(currentMap);
        window.__subnetMapHouse = {
            site: group.site,
            machines: machines,
            // The SVG export places the plan in the very same geographic
            // frame these dots sit in, instead of the overlay node's live
            // CSS box, which is stale after a panel toggle or resize.
            bounds: {
                n: bounds.getNorth(), s: bounds.getSouth(),
                e: bounds.getEast(), w: bounds.getWest()
            },
            planW: plan.w,
            planH: plan.h
        };
        return layer;
    }

    function enterHouse(key, group) {
        const map = currentMap;
        collapseAll(map);
        setExportCaption(true);
        const plan = housePlanOf(group);
        if (plan.logical) {
            // Data is static for the page's lifetime; build each
            // site's layout once and reuse it.
            plan.layout = layoutCache[group.site] ||
                (layoutCache[group.site] = buildLogicalLayout(group));
            plan.markup = plan.layout.markup;
            plan.w = plan.layout.w;
            plan.h = plan.layout.h;
        }
        const footprint = houseFootprint(plan);
        const bounds = houseBounds(group.lat, group.lon, footprint.w, footprint.h);

        house.activeKey = key;
        house.group = group;
        house.marker = clusterMarkers[key] || singleMarkers[key] || null;
        if (house.marker) {
            map.removeLayer(house.marker);
        }
        if (tileLayer) {
            map.removeLayer(tileLayer);
        }
        // The canton fill is a translucent red; left in place it would
        // tint the plain background behind the plan.
        cantonLayers.forEach((layer) => map.removeLayer(layer));
        mapContainer.classList.add('house-active');

        house.layer = L.layerGroup([
            L.rectangle(bounds.pad(0.9), {
                stroke: false, fillColor: '#f8f5ec',
                fillOpacity: 1, interactive: false
            })
        ]).addTo(map);
        house.planOverlay = createPlanOverlay(plan, bounds);
        house.planOverlay.attach(map);
        house.machines = addMachineMarkers(group, bounds, plan);

        const badge = document.createElement('div');
        badge.className = 'house-plan-badge';
        badge.appendChild(el('span', 'badge-site',
            (plan.logical ? t('floor_map', 'Floor map') : t('house_plan', 'House plan')) +
            ` \u2014 ${group.site}`));
        badge.appendChild(el('span', 'badge-hint',
            t('badge_hint', 'scroll out to return to the map')));
        mapContainer.appendChild(badge);
        house.badge = badge;

        // Frame the plan once on entry: zoom in as far as the plan
        // still fits within the fill fraction of the viewport.
        // Logical maps are usually tall, so they get more room.
        const size = map.getSize();
        const fill = plan.logical ? 0.75 : 0.6;
        let zoom = HOUSE_ENTER_ZOOM;
        for (let z = HOUSE_ENTER_ZOOM; z <= map.getMaxZoom(); z++) {
            const res = LV03_RESOLUTIONS[z];
            if (footprint.w > res * size.x * fill || footprint.h > res * size.y * fill) {
                break;
            }
            zoom = z;
        }
        map.setView(bounds.getCenter(), zoom);
    }

    function exitHouse() {
        if (!house.activeKey) {
            return;
        }
        const map = currentMap;
        const marker = house.marker;
        if (house.layer) {
            map.removeLayer(house.layer);
        }
        if (house.planOverlay) {
            house.planOverlay.detach(map);
        }
        if (house.machines) {
            map.removeLayer(house.machines);
        }
        resetHouseState();
        if (tileLayer) {
            tileLayer.addTo(map);
        }
        cantonLayers.forEach((layer) => layer.addTo(map));
        mapContainer.classList.remove('house-active');
        if (marker) {
            marker.addTo(map);
        }
        setExportCaption(false);
    }

    function updateHouseMode() {
        const map = currentMap;
        if (!map || isNaN(map.getZoom())) {
            return;
        }
        const zoom = map.getZoom();
        if (house.activeKey) {
            const far = map.distance(map.getCenter(),
                [house.group.lat, house.group.lon]) > HOUSE_LEAVE_M;
            if (zoom < HOUSE_EXIT_ZOOM || far) {
                exitHouse();
            }
            return;
        }
        if (zoom < HOUSE_ENTER_ZOOM) {
            return;
        }
        const center = map.getCenter();
        let best = null;
        Object.keys(groups).forEach((key) => {
            const dist = map.distance(center, [groups[key].lat, groups[key].lon]);
            if (dist <= HOUSE_ENTER_M && (!best || dist < best.dist)) {
                best = {key: key, dist: dist};
            }
        });
        if (best) {
            enterHouse(best.key, groups[best.key]);
        }
    }

    function fitView(map) {
        const bounds = L.latLngBounds(pins.map((pin) => [pin.lat, pin.lon]));
        if (!bounds.isValid()) {
            map.setView([46.95, 8.2], 8);
            return;
        }

        const crs = map.options.crs;
        if (crs && crs.code === 'EPSG:21781') {
            // Leaflet's getBoundsZoom assumes crs.scale(0) === 1,
            // which is false for the LV03 tile grid, so pick the
            // zoom from the projected spans manually. The grid is
            // rotated, so project all four bounds corners. Use an
            // integer zoom so tiles render at their native scale.
            const size = map.getSize();
            const corners = [
                bounds.getNorthWest(), bounds.getNorthEast(),
                bounds.getSouthWest(), bounds.getSouthEast()
            ].map((latlng) => crs.projection.project(latlng));
            const easting = corners.map((p) => p.x);
            const northing = corners.map((p) => p.y);
            const spanX = Math.max(...easting) - Math.min(...easting);
            const spanY = Math.max(...northing) - Math.min(...northing);

            let zoom = 0;
            for (let z = 0; z < LV03_RESOLUTIONS.length; z++) {
                const res = LV03_RESOLUTIONS[z];
                if (spanX / res <= size.x * 0.85 && spanY / res <= size.y * 0.85) {
                    zoom = z;
                } else {
                    break;
                }
            }
            zoom = Math.min(zoom, map.getMaxZoom());
            const centerProjected = L.point(
                (Math.min(...easting) + Math.max(...easting)) / 2,
                (Math.min(...northing) + Math.max(...northing)) / 2
            );
            map.setView(crs.projection.unproject(centerProjected), zoom);
        } else {
            map.fitBounds(bounds.pad(0.15));
        }
    }

    function buildMap() {
        if (currentMap) {
            currentMap.remove();
            currentMap = null;
            clearObj(grids);
            clearObj(expanded);
            clearObj(clusterMarkers);
            clearObj(singleMarkers);
            clearObj(layoutCache);
            resetHouseState();
            tileLayer = null;
            window.__subnetMapTiles = null;
            cantonLayers = [];
        }
        const map = typeof window.LV03 !== 'undefined'
            ? L.map('subnet-map', {
                crs: LV03_CRS,
                minZoom: 6,
                // Tiles go natively to 27 (0.25 m/px); the view
                // overzooms to 30 so the vector floor plan can be
                // inspected at close range.
                maxZoom: 30,
                zoomAnimation: false,
                maxBounds: COVERAGE_BOUNDS.pad(0.15),
                maxBoundsViscosity: 0.8
            })
            : L.map('subnet-map', {maxBounds: COVERAGE_BOUNDS.pad(0.15)});
        currentMap = map;

        const layer = L.tileLayer(SWISSSTOPO_URL, {
            minZoom: 0,
            maxZoom: 30,
            minNativeZoom: 8,
            maxNativeZoom: 27,
            bounds: COVERAGE_BOUNDS,
            attribution: '&copy; <a href="https://www.swisstopo.ch/">swisstopo</a>'
        });
        layer.getTileUrl = function (coords) {
            // The LV03 grid starts at tile 0/0 at its origin; the
            // WMTS server answers 400 for negative indices, which
            // happens at wide zooms and outside the country.
            if (coords.x < 0 || coords.y < 0) {
                return EMPTY_TILE;
            }
            return L.TileLayer.prototype.getTileUrl.call(this, coords);
        };
        layer.addTo(map);
        tileLayer = layer;
        // The exporter fetches the tile grid itself (see svg_export.js), so
        // its picture is not limited to the tiles this view happens to hold.
        // For that it needs to know how the grid is addressed.
        window.__subnetMapTiles = {
            url: SWISSSTOPO_URL,
            tileSize: layer.options.tileSize || 256,
            minNativeZoom: layer.options.minNativeZoom,
            maxNativeZoom: layer.options.maxNativeZoom
        };
        // Leaflet rebuilds the attribution control HTML whenever
        // layers are added; re-apply the new-tab target each time.
        const openAttributionLinks = () => {
            map.attributionControl.getContainer()
                .querySelectorAll('a')
                .forEach((link) => {
                    link.target = '_blank';
                    link.rel = 'noopener';
                });
        };
        map.on('layeradd', openAttributionLinks);
        openAttributionLinks();

        addCantonBorder(map);
        buildPins(map);
        // Clicking anywhere outside the pins collapses expanded
        // clusters again and closes the detail panel. (Suppressed
        // in house-plan mode, where the plan is the whole map.)
        map.on('click', () => {
            if (house.activeKey) {
                return;
            }
            collapseAll(map);
            closePanel();
        });
        map.on('zoomend', updateHouseMode);
        map.on('moveend', updateHouseMode);
        window.__subnetMap = map;
        fitView(map);
        setTimeout(() => map.invalidateSize(), 0);
    }

    let currentMap = null;
    let tileLayer = null;

    // How far the exported picture stands off the border it cuts along; the
    // served picture reads the same settings, so both agree.
    window.__subnetMapExportRoom = mapData.export_room || null;

    const boundaryUrl = mapData.canton_boundary_url;
    if (boundaryUrl) {
        fetch(boundaryUrl)
            .then((response) => (response.ok ? response.json() : null))
            .then((geojson) => {
                cantonBoundary = geojson;
                // Read by the SVG exporter to draw the border at the
                // exact position the map shows it.
                window.__subnetMapBoundary = geojson;
            })
            .catch(() => {
                cantonBoundary = null;
                window.__subnetMapBoundary = null;
            })
            .finally(() => {
                if (!currentMap) {
                    buildMap();
                }
            });
    } else {
        buildMap();
    }
})();
