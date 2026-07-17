"use strict";

// The faction graph (the dict emitted by FactionGraph.to_dict). The page is a small navigator over
// it: a sidebar lists each category, the detail pane renders one entity at a time, and every
// cross-reference (a producer, a trained unit, a recruited hero) is a link that selects its target.

let DATA = null;
let CURRENT = null; // { type, key } - or { type:"group", groupType, key:display }
let FACTIONS = null; // when a {factions:[...]} payload is loaded, the list of faction graphs
let GROUPS = {}; // category type -> Map(display name -> entries[]), rebuilt per faction
const HISTORY = [];

const el = (tag, props = {}, children = []) => {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(props)) {
        if (key === "dataset") Object.assign(node.dataset, value); // dataset is read-only; merge in
        else node[key] = value;
    }
    for (const child of [].concat(children)) {
        if (child == null) continue;
        node.append(child.nodeType ? child : document.createTextNode(child));
    }
    return node;
};

const byId = (id) => document.getElementById(id);
const fmtNum = (v) => (v == null ? "-" : (Math.round(v * 100) / 100).toString());

// --- navigation -------------------------------------------------------------------------------

function select(type, key, record = true) {
    if (record && CURRENT) HISTORY.push(CURRENT);
    CURRENT = { type, key };
    byId("back").disabled = HISTORY.length === 0;
    renderDetail();
    highlightSidebar();
}

// Open the disambiguation page for a display name shared by several objects of `type`.
function selectGroup(type, display, record = true) {
    if (record && CURRENT) HISTORY.push(CURRENT);
    CURRENT = { type: "group", groupType: type, key: display };
    byId("back").disabled = HISTORY.length === 0;
    renderDetail();
    highlightSidebar();
}

function back() {
    const prev = HISTORY.pop();
    if (prev && prev.type === "group") selectGroup(prev.groupType, prev.key, false);
    else if (prev) select(prev.type, prev.key, false);
    byId("back").disabled = HISTORY.length === 0;
}

// A clickable reference to another entity. `note` is dimmed trailing context (a button name, etc.).
function ref(type, key, label, note) {
    const exists = type === "overview" || (DATA[pluralOf(type)] || {})[key] !== undefined;
    if (!exists) {
        return el("span", {}, [label || key, note ? el("span", { className: "ref-note" }, ` ${note}`) : null]);
    }
    const link = el("a", { className: "ref", onclick: () => select(type, key) }, label || key);
    return el("span", {}, [link, note ? el("span", { className: "ref-note" }, ` ${note}`) : null]);
}

const pluralOf = (type) => ({ structure: "structures", unit: "units", hero: "heroes", upgrade: "upgrades", created: "created" }[type]);

// --- detail pane ------------------------------------------------------------------------------

function fact(label, value) {
    return el("div", { className: "fact" }, [
        el("span", { className: "label" }, label),
        el("span", { className: "value" }, value),
    ]);
}

function block(title, items, emptyNote) {
    if (!items.length) return emptyNote ? el("section", { className: "block" }, [el("h3", {}, title), el("p", { className: "muted" }, emptyNote)]) : null;
    return el("section", { className: "block" }, [
        el("h3", {}, `${title} (${items.length})`),
        el("ul", { className: "refs" }, items.map((it) => el("li", {}, it))),
    ]);
}

function header(kind, title, id) {
    return el("div", {}, [
        el("div", { className: "card-kind" }, kind),
        el("h2", { className: "card-title" }, title),
        id ? el("div", { className: "card-id" }, id) : null,
    ]);
}

// The object's Description / RecruitText, shown under the header. Newlines are preserved (the
// string table's metadata + lore lines) via CSS white-space: pre-line. Empty → nothing rendered.
function descriptionBlock(text) {
    return text ? el("p", { className: "description" }, text) : null;
}

// "CAVALRY_RANGED" -> "Cavalry Ranged" - a readable damage-type name.
function prettyType(type) {
    return String(type).toLowerCase().replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

// The plain-language stat snapshot (sage_ui UnitPanel mirrored): a stats grid, the main attack,
// what it is tough/weak against, and its abilities. `opts.abilities=false` omits abilities (a
// structure lists them separately). Returns an array of nodes to splat into a detail card.
function profileBlocks(profile, opts = {}) {
    const out = [];
    const facts = [];
    const push = (label, value) => value != null && facts.push(fact(label, fmtNum(value)));
    push("Health", profile.health);
    push("Speed", profile.speed);
    push("Sight range", profile.vision);
    push("Cost", profile.build_cost);
    push("Build time", profile.build_time);
    push("Command points", profile.command_points);
    if (facts.length) out.push(el("div", { className: "facts" }, facts));

    if (profile.weapons && profile.weapons.length) {
        out.push(block("Weapons", profile.weapons.map(weaponNode)));
    }
    const durability = durabilityBlock(profile.defenses, profile.health);
    if (durability) out.push(durability);
    if (opts.abilities !== false && profile.abilities && profile.abilities.length) {
        out.push(abilityBlock(profile.abilities));
    }
    return out;
}

function weaponNode(weapon) {
    const kind = weapon.kind === "melee" ? "Melee attack" : "Ranged attack";
    const parts = [`${fmtNum(weapon.damage)}${weapon.damage_type ? " " + prettyType(weapon.damage_type) : ""} damage`];
    if (weapon.range) parts.push(`range ${fmtNum(weapon.range)}`);
    if (weapon.dps) parts.push(`~${fmtNum(weapon.dps)} dps`);
    return el("span", {}, [el("strong", {}, `${kind}: `), parts.join(", ")]);
}

// "Tough against" / "Weak against" lines, derived from the effective-health-per-type list relative
// to the object's base health. Null when nothing stands out.
function durabilityBlock(defenses, health) {
    if (!defenses || !defenses.length) return null;
    const tough = defenses.filter((d) => d.effective_health > (health || 0) * 1.05).map((d) => prettyType(d.damage_type));
    const weak = defenses.filter((d) => health && d.effective_health < health * 0.95).map((d) => prettyType(d.damage_type));
    if (!tough.length && !weak.length) return null;
    const lines = [];
    if (tough.length) lines.push(el("li", {}, [el("strong", {}, "Tough against: "), tough.join(", ")]));
    if (weak.length) lines.push(el("li", {}, [el("strong", {}, "Weak against: "), weak.join(", ")]));
    return el("section", { className: "block" }, [el("h3", {}, "Durability"), el("ul", { className: "refs" }, lines)]);
}

// A link to whichever graph category holds `name` (unit/hero/structure/upgrade), else plain text -
// so a created object or transform form is navigable when it is itself a graph node.
function anyRef(name, label) {
    for (const type of ["unit", "hero", "structure", "upgrade", "created"]) {
        if ((DATA[pluralOf(type)] || {})[name]) return ref(type, name, label);
    }
    return document.createTextNode(label || name);
}

function joinNodes(nodes, sep) {
    const out = [];
    nodes.forEach((node, i) => { if (i) out.push(sep); out.push(node); });
    return out;
}

// The concrete effect lines of a power: what it turns into, what it creates, the weapon it fires,
// and the stat buffs it grants. Each created object / form is a link.
function effectLines(power) {
    const lines = [];
    const link = (entries) => joinNodes(entries.map((e) => anyRef(e.name, e.display)), ", ");
    if (power.transforms_into && power.transforms_into.length) {
        lines.push(el("div", { className: "effect-line" }, [el("strong", {}, "Transforms into: "), ...link(power.transforms_into)]));
    }
    if (power.creates && power.creates.length) {
        lines.push(el("div", { className: "effect-line" }, [el("strong", {}, "Creates: "), ...link(power.creates)]));
    }
    if (power.weapon) {
        lines.push(el("div", { className: "effect-line" }, [weaponNode(power.weapon)]));
    }
    if (power.modifiers && power.modifiers.length) {
        const text = power.modifiers.map((m) => `${prettyType(m.stat)} ${m.amount}`).join(", ");
        lines.push(el("div", { className: "effect-line" }, [el("strong", {}, "Grants: "), text]));
    }
    return lines;
}

function abilityBlock(abilities, title = "Abilities") {
    return el("section", { className: "block" }, [
        el("h3", {}, `${title} (${abilities.length})`),
        el("ul", { className: "refs" }, abilities.map((a) => {
            const cd = (a.cooldown && a.cooldown >= 1)
                ? el("span", { className: "ref-note" }, ` · recharge ${fmtNum(a.cooldown)}s`) : null;
            const effect = a.effect
                ? el("div", { className: "description", textContent: a.effect.replace(/\\n/g, "\n").trim() }) : null;
            return el("li", { className: "ability" }, [el("strong", {}, a.display), cd, ...effectLines(a), effect]);
        })),
    ]);
}

function renderDetail() {
    const pane = byId("detail");
    pane.innerHTML = "";
    const render = DETAIL[CURRENT.type];
    pane.append(render());
    pane.scrollTop = 0;
}

const DETAIL = {
    overview() {
        const sp = DATA.start_points || [];
        const wrap = el("div", {}, [
            header("Faction", DATA.display || DATA.name, `${DATA.name} · side: ${DATA.side ?? "-"}`),
            el("div", { className: "facts" }, [
                fact("Structures", String(Object.keys(DATA.structures || {}).length)),
                fact("Units", String(Object.keys(DATA.units || {}).length)),
                fact("Heroes", String(Object.keys(DATA.heroes || {}).length)),
                fact("Upgrades", String(Object.keys(DATA.upgrades || {}).length)),
                fact("Start points", String(sp.length)),
            ]),
        ]);
        if (DATA.spellbook && DATA.spellbook.powers && DATA.spellbook.powers.length) {
            wrap.append(abilityBlock(DATA.spellbook.powers, "Spellbook powers"));
        }
        wrap.append(el("section", { className: "block" }, [
            el("h3", {}, `Start points (${sp.length})`),
            el("ul", { className: "refs" }, sp.map((p) => el("li", {}, [
                el("span", { className: "tag" }, p.kind), " ", el("strong", {}, p.flag),
                " → ", p.base || p.structure || "?",
                p.citadel ? el("span", {}, [" · citadel ", ref("structure", p.citadel)]) : null,
            ]))),
        ]));
        return wrap;
    },

    structure() {
        const s = DATA.structures[CURRENT.key];
        return el("div", {}, [
            header(`Structure · ${s.role}`, s.display, s.name),
            descriptionBlock(s.description),
            s.variation ? el("p", { className: "ref-note" }, `Build variation: ${s.variation}`) : null,
            ...(s.profile ? profileBlocks(s.profile, { abilities: false }) : []),
            block("Trains units", s.trains_units.map((n) => ref("unit", n))),
            block("Recruits heroes", s.recruits_heroes.map((n) => ref("hero", n))),
            block("Researches upgrades", s.researches_upgrades.map((n) => ref("upgrade", n))),
            (s.abilities && s.abilities.length) ? abilityBlock(s.abilities) : null,
        ]);
    },

    unit() {
        const u = DATA.units[CURRENT.key];
        return el("div", {}, [
            header("Unit", u.display, u.name),
            descriptionBlock(u.description),
            ...(u.profile ? profileBlocks(u.profile) : []),
            producerBlock(u.producers),
        ]);
    },

    hero() {
        const h = DATA.heroes[CURRENT.key];
        return el("div", {}, [
            header("Hero", h.display, h.name),
            descriptionBlock(h.description),
            ...(h.profile ? profileBlocks(h.profile) : []),
            producerBlock(h.producers, "Recruited at"),
        ]);
    },

    upgrade() {
        const u = DATA.upgrades[CURRENT.key];
        return el("div", {}, [
            header("Upgrade", u.display, u.name),
            descriptionBlock(u.description),
            el("div", { className: "facts" }, [fact("Cost", fmtNum(u.cost))]),
            producerBlock(u.producers, "Researched at"),
        ]);
    },

    created() {
        const c = DATA.created[CURRENT.key];
        return el("div", {}, [
            header("Summoned / form", c.display, c.name),
            descriptionBlock(c.description),
            ...(c.profile ? profileBlocks(c.profile) : []),
        ]);
    },
};

function producerBlock(producers, title = "Produced at") {
    return block(title, (producers || []).map((p) =>
        ref("structure", p.structure, null, p.shortcut ? `· ${p.button} (${p.shortcut})` : `· ${p.button}`)),
        "No producer found.");
}

// Disambiguation page: the distinct objects that share one display name, each a link to its own
// detail, annotated with what tells them apart (their id plus type-specific facts).
DETAIL.group = function () {
    const type = CURRENT.groupType;
    const display = CURRENT.key;
    const members = (GROUPS[type] && GROUPS[type].get(display)) || [];
    return el("div", {}, [
        header(`${type} · ${members.length} variants`, display),
        el("p", { className: "muted" }, "Several objects share this name - pick a variant:"),
        el("ul", { className: "refs" }, members.map((member) =>
            el("li", {}, memberRow(type, member)))),
    ]);
};

function memberRow(type, member) {
    const link = el("a", { className: "ref", onclick: () => select(type, member.name) }, member.name);
    const facts = memberFacts(type, member);
    return el("span", {}, [link, facts ? el("span", { className: "ref-note" }, ` · ${facts}` ) : null]);
}

function memberFacts(type, member) {
    if (type === "unit") {
        const bits = [];
        if (member.cost != null) bits.push(`cost ${fmtNum(member.cost)}`);
        if (member.command_points != null) bits.push(`cp ${fmtNum(member.command_points)}`);
        return bits.join(" · ");
    }
    if (type === "upgrade") return member.cost != null ? `cost ${fmtNum(member.cost)}` : "";
    if (type === "structure") return member.role || "";
    return "";
}

function groupByDisplay(entries) {
    const map = new Map();
    for (const entry of entries) {
        const key = entry.display || entry.name;
        if (!map.has(key)) map.set(key, []);
        map.get(key).push(entry);
    }
    return map;
}

// --- sidebar ----------------------------------------------------------------------------------

const CATEGORIES = [
    { type: "overview", label: "Overview" },
    { type: "structure", label: "Structures", plural: "structures" },
    { type: "unit", label: "Units", plural: "units" },
    { type: "hero", label: "Heroes", plural: "heroes" },
    { type: "upgrade", label: "Upgrades", plural: "upgrades" },
    { type: "created", label: "Summoned & forms", plural: "created" },
];

function renderSidebar() {
    const nav = byId("sidebar");
    nav.innerHTML = "";
    GROUPS = {};
    for (const cat of CATEGORIES) {
        if (cat.type === "overview") {
            const btn = el("button", { dataset: { type: "overview", group: "" }, onclick: () => select("overview", "") }, cat.label);
            nav.append(el("div", { className: "cat-items" }, [btn]));
            continue;
        }
        // Group entries by exact display name; a name shared by several objects becomes one entry
        // that opens a disambiguation page instead of N duplicate rows.
        const groups = groupByDisplay(Object.values(DATA[cat.plural] || {}));
        GROUPS[cat.type] = groups;
        const names = [...groups.keys()].sort((a, b) => a.localeCompare(b));
        if (!names.length) continue;  // skip an empty category (e.g. no summoned objects)
        const items = el("div", { className: "cat-items" }, names.map((display) => {
            const members = groups.get(display);
            const single = members.length === 1;
            const search = (display + " " + members.map((m) => m.name).join(" ")).toLowerCase();
            return el("button", {
                dataset: { type: cat.type, group: display, search },
                onclick: () => (single ? select(cat.type, members[0].name) : selectGroup(cat.type, display)),
            }, [display, single ? null : el("span", { className: "dup-count" }, ` ${members.length}`)]);
        }));
        const head = el("div", { className: "cat-header" }, [
            el("span", {}, cat.label),
            el("span", { className: "count" }, String(names.length)),
        ]);
        head.onclick = () => items.classList.toggle("collapsed");
        nav.append(head, items);
    }
    highlightSidebar();
}

// The display name of whatever is selected - the key the sidebar groups on - so the matching button
// highlights whether a single object, one of a group's variants, or the group page itself is open.
function currentDisplay() {
    if (!CURRENT) return null;
    if (CURRENT.type === "group") return CURRENT.key;
    if (CURRENT.type === "overview") return "";
    const plural = pluralOf(CURRENT.type);
    const item = plural && DATA[plural] && DATA[plural][CURRENT.key];
    return item ? (item.display || item.name) : null;
}

function highlightSidebar() {
    const type = CURRENT && (CURRENT.type === "group" ? CURRENT.groupType : CURRENT.type);
    const display = currentDisplay();
    for (const btn of document.querySelectorAll("#sidebar button")) {
        const active = type != null && btn.dataset.type === type && btn.dataset.group === display;
        btn.classList.toggle("active", !!active);
    }
}

function applySearch(term) {
    term = term.trim().toLowerCase();
    for (const btn of document.querySelectorAll("#sidebar .cat-items button[data-search]")) {
        const hit = !term || btn.dataset.search.includes(term);
        btn.classList.toggle("hidden", !hit);
    }
}

// --- bootstrap --------------------------------------------------------------------------------

// A payload is either a single faction graph or a {factions:[...]} wrapper. The wrapper opens onto a
// faction chooser (and a header dropdown to switch); a single graph loads straight into the navigator.
function loadPayload(payload) {
    if (payload && Array.isArray(payload.factions)) {
        FACTIONS = payload.factions;
        setupFactionPicker();
        renderFactionChooser();
    } else {
        FACTIONS = null;
        byId("faction-select").hidden = true;
        loadSingle(payload);
    }
}

function setupFactionPicker() {
    const select = byId("faction-select");
    select.innerHTML = "";
    select.append(el("option", { value: "", textContent: "- Select faction -" }));
    FACTIONS.forEach((faction, index) => {
        select.append(el("option", { value: String(index), textContent: faction.display || faction.name }));
    });
    select.value = "";
    select.hidden = false;
    select.onchange = () => (select.value === "" ? renderFactionChooser() : selectFaction(Number(select.value)));
}

function renderFactionChooser() {
    DATA = null;
    FACTIONS && (byId("faction-select").value = "");
    byId("sidebar").innerHTML = "";
    byId("faction-name").textContent = "sage_mods.edain";
    byId("faction-side").textContent = "";
    byId("back").disabled = true;
    HISTORY.length = 0;
    document.title = "sage_mods.edain - choose a faction";
    const grid = el("div", { className: "faction-grid" }, FACTIONS.map((faction, index) =>
        el("button", { className: "faction-card", onclick: () => selectFaction(index) }, [
            el("div", { className: "name" }, faction.display || faction.name),
            el("div", { className: "side" }, faction.side || ""),
            el("div", { className: "counts" },
                `${Object.keys(faction.structures || {}).length} structures · ` +
                `${Object.keys(faction.units || {}).length} units · ` +
                `${Object.keys(faction.heroes || {}).length} heroes`),
        ])));
    const pane = byId("detail");
    pane.innerHTML = "";
    pane.append(el("div", {}, [el("h2", { className: "card-title" }, "Select a faction"), grid]));
}

function selectFaction(index) {
    if (FACTIONS) byId("faction-select").value = String(index);
    loadSingle(FACTIONS[index]);
}

function loadSingle(data) {
    DATA = data;
    HISTORY.length = 0;
    byId("faction-name").textContent = data.display || data.name || "faction";
    byId("faction-side").textContent = data.side ? `· ${data.side}` : "";
    document.title = `${data.display || data.name} - sage_mods.edain`;
    renderSidebar();
    select("overview", "", false);
}

byId("back").onclick = back;
byId("search").addEventListener("input", (e) => applySearch(e.target.value));
byId("file").addEventListener("change", (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
        try { loadPayload(JSON.parse(reader.result)); }
        catch (err) { byId("detail").innerHTML = `<p class="empty">Could not parse JSON: ${err}</p>`; }
    };
    reader.readAsText(file);
});

// When served by `sage-edain serve`, the payload is at ./graph.json; opened as a bare file that
// fetch fails, and the user loads a file by hand instead.
fetch("graph.json").then((r) => (r.ok ? r.json() : Promise.reject())).then(loadPayload).catch(() => {
    byId("detail").innerHTML =
        '<p class="empty">No <code>graph.json</code> found next to this page. Use <em>Load graph.json</em> above.</p>';
});
