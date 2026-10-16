// getRandomValues is available on LAN HTTP as well as HTTPS. randomUUID is
// restricted to secure contexts and can throw before an order is even sent.
export function createSubmissionId(cryptoProvider = globalThis.crypto) {
  if (typeof cryptoProvider?.getRandomValues !== "function")
    throw new Error("This browser cannot generate an order ID. Update the browser and retry.");
  const bytes = cryptoProvider.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  return Array.from(bytes, value => value.toString(16).padStart(2, "0")).join("");
}
