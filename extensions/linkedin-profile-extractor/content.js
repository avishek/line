const SECTION_ALIASES = {
  "About": ["about"],
  "Experience": ["experience"],
  "Education": ["education"],
  "Licenses & Certifications": ["licenses & certifications", "licenses & certification", "certifications"],
  "Projects": ["projects"],
  "Skills": ["skills"],
  "Recommendations": ["recommendations"],
  "Courses": ["courses"],
  "Languages": ["languages"],
  "Interests": ["interests"],
  "Causes": ["causes"],
};

/** Section name -> possible DOM id (LinkedIn uses these for anchor links / details views). */
const SECTION_IDS = {
  "About": "about",
  "Experience": "experience",
  "Education": "education",
  "Licenses & Certifications": "licenses",
  "Projects": "projects",
  "Skills": "skills",
  "Recommendations": "recommendations",
  "Courses": "courses",
  "Languages": "languages",
  "Interests": "interests",
  "Causes": "causes",
};

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg?.type !== "extract_profile") return;

  extractProfile(msg.extractorVersion)
    .then((data) => sendResponse({ ok: true, data }))
    .catch((err) => sendResponse({ ok: false, error: err.message || "Extraction error" }));

  return true;
});

async function extractProfile(extractorVersion) {
  const extractionWarnings = [];

  await autoScroll();
  await expandAllVisibleButtons();
  await sleep(1500);

  const metadata = {
    sourceUrl: location.href,
    profileSlug: getProfileSlug(location.href),
    extractedAt: new Date().toISOString(),
    extractorVersion,
  };

  const sections = {};

  for (const [sectionName, aliases] of Object.entries(SECTION_ALIASES)) {
    const sectionNode = findSection(sectionName, aliases);
    if (!sectionNode) {
      sections[sectionName] = [];
      extractionWarnings.push(`${sectionName}: section not found`);
      continue;
    }

    const parsed = parseSectionItems(sectionNode, sectionName);
    sections[sectionName] = parsed;

    if (!parsed.length) {
      extractionWarnings.push(`${sectionName}: section found but no entries parsed`);
    }
  }

  return { metadata, sections, extractionWarnings };
}

function parseSectionItems(sectionNode, sectionName) {
  const itemSelectors = [
    "li",
    ".pvs-list__paged-list-item",
    ".pvs-entity",
    "[class*='pvs-list'] > div",
  ];
  let liItems = [];
  for (const sel of itemSelectors) {
    liItems = Array.from(sectionNode.querySelectorAll(sel));
    if (liItems.length) break;
  }
  if (!liItems.length) {
    const text = sectionNode.innerText?.trim();
    return text ? [{ text }] : [];
  }

  const uniqueItems = [];
  const seen = new Set();

  liItems.forEach((li) => {
    const entry = parseListItem(li, sectionName);
    const signature = JSON.stringify(entry);
    if (!signature || signature === "{}" || seen.has(signature)) return;
    seen.add(signature);
    uniqueItems.push(entry);
  });

  return uniqueItems;
}

function parseListItem(li, sectionName) {
  const raw = normalizedLines(li.innerText || "");
  const links = Array.from(li.querySelectorAll("a[href]"))
    .map((a) => a.href)
    .filter(Boolean)
    .slice(0, 5);

  if (!raw.length) {
    return links.length ? { links } : {};
  }

  const [line1, line2, line3, ...rest] = raw;

  if (sectionName === "Skills") {
    return { skill: line1, context: rest.length ? [line2, line3, ...rest].filter(Boolean) : [] };
  }

  if (sectionName === "Recommendations") {
    return {
      snippet: line1,
      byline: line2 || "",
      details: [line3, ...rest].filter(Boolean),
      links,
    };
  }

  if (sectionName === "About") {
    return { text: raw.join(" ") };
  }

  return {
    title: line1 || "",
    subtitle: line2 || "",
    meta: line3 || "",
    details: rest,
    links,
  };
}

function findSection(sectionName, aliases) {
  const normalizedAliases = aliases.map(normalize);

  const id = SECTION_IDS[sectionName];
  if (id) {
    const byId = document.getElementById(id) || document.querySelector(`section[id="${id}"]`);
    if (byId) return byId;
  }

  const sectionCandidates = Array.from(
    document.querySelectorAll(
      "section, div.artdeco-card, [class*='accordion-panel'], [class*='pv-profile-section'], [class*='scaffold-layout__main'] div[class*='card']"
    )
  );

  for (const node of sectionCandidates) {
    const heading = node.querySelector("h1, h2, h3, h4, span[aria-hidden='true'], [class*='accordion-header']");
    if (heading) {
      const text = normalize(heading.textContent || "");
      if (normalizedAliases.some((alias) => text.includes(alias))) return node;
    }
    const firstLine = normalizedLines(node.innerText || "")[0] || "";
    if (normalizedAliases.some((alias) => normalize(firstLine).includes(alias))) return node;
  }

  return null;
}

async function autoScroll() {
  let lastHeight = 0;
  for (let i = 0; i < 8; i += 1) {
    window.scrollTo({ top: document.body.scrollHeight, behavior: "smooth" });
    await sleep(500);

    const newHeight = document.body.scrollHeight;
    if (newHeight === lastHeight) break;
    lastHeight = newHeight;
  }

  window.scrollTo({ top: 0, behavior: "instant" });
}

async function expandAllVisibleButtons() {
  const patterns = [
    "see more",
    "show more",
    "show all",
    "more",
    "show all experiences",
    "show all education",
    "show all skills",
  ];

  const candidates = Array.from(document.querySelectorAll("button, a"));

  for (const node of candidates) {
    const label = normalize(node.innerText || node.getAttribute("aria-label") || "");
    if (!patterns.some((p) => label.includes(p))) continue;
    if (node.offsetParent === null) continue;

    try {
      node.click();
      await sleep(200);
    } catch {
      // Ignore click failures from stale nodes.
    }
  }
}

function normalizedLines(text) {
  return text
    .split("\n")
    .map((line) => line.replace(/\s+/g, " ").trim())
    .filter(Boolean);
}

function getProfileSlug(url) {
  try {
    const pathname = new URL(url).pathname;
    const parts = pathname.split("/").filter(Boolean);
    if (parts[0] === "in" && parts[1]) {
      return parts[1].toLowerCase().replace(/[^a-z0-9-]/g, "-");
    }
  } catch {
    return "unknown";
  }
  return "unknown";
}

function normalize(text) {
  return String(text).replace(/\s+/g, " ").trim().toLowerCase();
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
