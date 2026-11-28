/** Snapshot of the Minzdrav classifier laid out as shelves and search groups. */

export interface CatalogDocument {
  id: string;
  name: string;
  age: string;
  year: string;
  mkb10: string[];
}

export interface CatalogGroup {
  catalogKey: string;
  shelfKey: string;
  name: string;
  codes: string;
  documents: CatalogDocument[];
}

export interface CatalogShelf {
  catalogKey: string;
  id: string;
  name: string;
  range: string;
}

export interface CatalogSnapshot {
  snapshot: string;
  shelves: CatalogShelf[];
  groups: CatalogGroup[];
}
