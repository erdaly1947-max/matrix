const DEFAULT_MAX_ENTRIES = 2_000;
const DEFAULT_MAX_BYTES = 32 * 1024 * 1024;
const ENTRY_OVERHEAD_BYTES = 128;

function estimateEntryBytes(key, entry) {
  const body = typeof entry?.body === "string" ? entry.body : String(entry?.body ?? "");
  // Account conservatively for JavaScript string storage plus key/object overhead.
  return (Buffer.byteLength(body, "utf8") * 2)
    + Buffer.byteLength(String(key), "utf8")
    + ENTRY_OVERHEAD_BYTES;
}

/** FIFO cache bounded by both entry count and an approximate in-memory byte budget. */
export class BoundedRestCache {
  #entries = new Map();
  #bytes = 0;
  #maxEntries;
  #maxBytes;

  constructor({ maxEntries = DEFAULT_MAX_ENTRIES, maxBytes = DEFAULT_MAX_BYTES } = {}) {
    if (!Number.isSafeInteger(maxEntries) || maxEntries < 1) {
      throw new TypeError("maxEntries must be a positive safe integer");
    }
    if (!Number.isSafeInteger(maxBytes) || maxBytes < 1) {
      throw new TypeError("maxBytes must be a positive safe integer");
    }
    this.#maxEntries = maxEntries;
    this.#maxBytes = maxBytes;
  }

  get size() {
    return this.#entries.size;
  }

  get bytes() {
    return this.#bytes;
  }

  get maxBytes() {
    return this.#maxBytes;
  }

  get(key, now = Date.now()) {
    const entry = this.#entries.get(key);
    if (!entry) return null;
    if (Number.isFinite(entry.expiresAt) && entry.expiresAt <= now) {
      this.delete(key);
      return null;
    }
    return entry;
  }

  set(key, entry, now = Date.now()) {
    this.delete(key);
    this.#removeExpired(now);

    const size = estimateEntryBytes(key, entry);
    if (size > this.#maxBytes) return false;

    while (
      this.#entries.size >= this.#maxEntries
      || this.#bytes + size > this.#maxBytes
    ) {
      const oldestKey = this.#entries.keys().next().value;
      if (oldestKey === undefined) break;
      this.delete(oldestKey);
    }

    this.#entries.set(key, entry);
    this.#bytes += size;
    return true;
  }

  delete(key) {
    const entry = this.#entries.get(key);
    if (!entry) return false;
    this.#entries.delete(key);
    this.#bytes = Math.max(0, this.#bytes - estimateEntryBytes(key, entry));
    return true;
  }

  clear() {
    this.#entries.clear();
    this.#bytes = 0;
  }

  #removeExpired(now) {
    for (const [key, entry] of this.#entries) {
      if (Number.isFinite(entry.expiresAt) && entry.expiresAt <= now) {
        this.delete(key);
      }
    }
  }
}

export { DEFAULT_MAX_ENTRIES as REST_CACHE_MAX_ENTRIES, DEFAULT_MAX_BYTES as REST_CACHE_MAX_BYTES };
