/**
 * Background parsing of uploaded documents: extract the text, split it into
 * sections. Documents wait in a queue and a few are processed at a time, so a
 * batch upload returns at once. The queue lives in memory; documents left
 * "queued" or "processing" by a previous run are queued again at startup.
 */
import type { Extractor } from "./extract.ts";
import { StoreError, type Store } from "./store.ts";

export class Jobs {
  private readonly queue: string[] = [];
  private running = 0;
  private idle: (() => void)[] = [];

  constructor(
    private readonly store: Store,
    private readonly extract: Extractor,
    private readonly concurrency = 2,
  ) {}

  /** Queue everything a previous run left unfinished. */
  resume(): void {
    for (const doc of this.store.allDocuments()) {
      if (doc.job.state === "queued" || doc.job.state === "processing") this.add(doc.id);
    }
  }

  add(docId: string): void {
    if (!this.queue.includes(docId)) this.queue.push(docId);
    this.store.setJob(docId, "queued");
    this.pump();
  }

  /** Resolves when nothing is queued or running (for tests). */
  whenIdle(): Promise<void> {
    if (!this.running && !this.queue.length) return Promise.resolve();
    return new Promise((resolve) => this.idle.push(resolve));
  }

  private pump(): void {
    while (this.running < this.concurrency && this.queue.length) {
      const docId = this.queue.shift()!;
      this.running += 1;
      void this.process(docId).finally(() => {
        this.running -= 1;
        this.pump();
        if (!this.running && !this.queue.length) {
          const waiting = this.idle;
          this.idle = [];
          for (const resolve of waiting) resolve();
        }
      });
    }
  }

  private async process(docId: string): Promise<void> {
    try {
      const doc = this.store.doc(docId);
      this.store.setJob(docId, "processing");
      const extracted = await this.extract(this.store.sourcePath(doc));
      this.store.setText(docId, extracted.text, extracted.pages);
    } catch (error) {
      // The document may have been deleted while it was being read.
      if (error instanceof StoreError && error.status === 404) return;
      this.store.setJob(docId, "failed", error instanceof Error ? error.message : String(error));
    }
  }
}
