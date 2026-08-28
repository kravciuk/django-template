// Mirrors the JSON shapes built server-side by
// apps.content.templatetags.header_tags.header_context (header-data) and
// apps.content.home_data.build_home_payload (home-data), embedded via
// Django's `json_script` filter - see templates/base.html / content/home.html.

export interface Breadcrumb {
  label: string;
  url: string | null;
}

export interface NavData {
  active: "notes" | "documents" | null;
  notes_url: string;
  documents_url: string;
  add_note_url: string;
  add_document_url: string;
  login_url: string;
  is_authenticated: boolean;
  display_name: string | null;
  initial: string | null;
}

export interface HeaderData {
  nav: NavData;
  breadcrumbs: Breadcrumb[];
}

export interface NoteCard {
  public_id: string;
  title: string;
  kind_label: string;
  created_at_display: string;
  excerpt: string;
  has_cover: boolean;
  cover_url: string | null;
  detail_url: string;
}

export interface RecentDocument {
  title: string;
  date_display: string;
  detail_url: string;
}

export interface ExpiringDocument {
  title: string;
  expires_at_display: string;
  days_left: number;
  detail_url: string;
}

export interface DocumentsBlock {
  recent: RecentDocument[];
  expiring: ExpiringDocument[];
}

export interface HomeData {
  notes: NoteCard[];
  documents: DocumentsBlock | null;
}

/** Reads a Django `json_script`-embedded payload by its element id. Returns
 * null if the page has no such element (e.g. home-data on non-home pages). */
export function readJson<T>(elementId: string): T | null {
  const el = document.getElementById(elementId);
  if (!el || !el.textContent) return null;
  return JSON.parse(el.textContent) as T;
}
