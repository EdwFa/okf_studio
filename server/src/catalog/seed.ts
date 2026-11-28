/**
 * Creates the classifier shelves and groups in the studio.
 * A second run finds them by catalogKey and leaves names a person edited alone.
 * Domains and groups without a catalogKey are not renamed, hidden, or removed.
 */
import { catalogSnapshot } from "./assign.ts";
import { Store, StoreError, type Domain, type Group } from "../store.ts";

export interface SeedResult {
  created: { domains: number; groups: number };
  existing: { domains: number; groups: number };
}

function place<T>(create: (name: string) => T, name: string, disambiguator: string): T {
  try {
    return create(name);
  } catch (error) {
    if (error instanceof StoreError && error.status === 409) return create(`${name} (${disambiguator})`.slice(0, 120));
    throw error;
  }
}

export function seedCatalog(store: Store): SeedResult {
  const snapshot = catalogSnapshot();
  const result: SeedResult = { created: { domains: 0, groups: 0 }, existing: { domains: 0, groups: 0 } };
  const domains = (): Domain[] => store.catalogView().domains;

  for (const shelf of snapshot.shelves) {
    let domain = domains().find((item) => item.catalogKey === shelf.catalogKey);
    if (domain) {
      result.existing.domains += 1;
    } else {
      domain = place(
        (name) => store.createDomain({ name, description: shelf.range, catalogKey: shelf.catalogKey }),
        shelf.name,
        shelf.range,
      );
      result.created.domains += 1;
    }
    const domainId = domain.id;
    for (const group of snapshot.groups.filter((item) => item.shelfKey === shelf.catalogKey)) {
      const current = domains().find((item) => item.id === domainId);
      const found: Group | undefined = current?.groups.find((item) => item.catalogKey === group.catalogKey);
      if (found) {
        result.existing.groups += 1;
        continue;
      }
      place(
        (name) => store.createGroup(domainId, { name, description: group.codes, hidden: true, catalogKey: group.catalogKey }),
        group.name,
        group.codes,
      );
      result.created.groups += 1;
    }
  }
  return result;
}
