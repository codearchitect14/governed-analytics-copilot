export interface ContactPayload {
  name: string;
  email: string;
  company: string | null;
  topic: string;
  message: string;
  consent: true;
}

/** Sends a contact request. Throws when the server does not accept it. */
export async function submitContact(payload: ContactPayload): Promise<void> {
  const response = await fetch("/api/v1/public/contact", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    credentials: "same-origin",
  });
  if (!response.ok) {
    throw new Error(`contact request failed with status ${response.status}`);
  }
}
