"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

const TOTAL = 781;

export function Classifier({ treeHtml, rubricCount }: { treeHtml: string; rubricCount: number }) {
  const treeRef = useRef<HTMLUListElement>(null);
  const wasFiltering = useRef(false);
  const [query, setQuery] = useState("");
  const [age, setAge] = useState("all");
  const [shown, setShown] = useState(`Показано ${TOTAL} из ${TOTAL}`);
  const [empty, setEmpty] = useState(false);

  function showTwoLevels() {
    const tree = treeRef.current;
    if (!tree) return;
    tree.querySelectorAll<HTMLDetailsElement>("li.chapter > details").forEach((node) => {
      node.open = true;
    });
    tree.querySelectorAll<HTMLDetailsElement>("li.block > details, li.rubric > details").forEach((node) => {
      node.open = false;
    });
  }

  function showThreeLevels() {
    const tree = treeRef.current;
    if (!tree) return;
    tree.querySelectorAll<HTMLDetailsElement>("li.chapter > details, li.block > details").forEach((node) => {
      node.open = true;
    });
    tree.querySelectorAll<HTMLDetailsElement>("li.rubric > details").forEach((node) => {
      node.open = false;
    });
  }

  function showDoc(doc: HTMLElement, ageOk: boolean, textOk: boolean) {
    const show = ageOk && textOk;
    doc.classList.toggle("is-hidden", !show);
    return show;
  }

  useEffect(() => {
    const tree = treeRef.current;
    if (!tree) return;
    const text = query.trim().toLowerCase();
    const filtering = text !== "" || age !== "all";
    let visibleDocs = 0;

    function setCount(node: HTMLElement, visible: number) {
      const el = node.querySelector<HTMLElement>(":scope > details > summary > .count");
      if (!el) return;
      el.textContent = filtering ? `${visible}/${node.dataset.total}` : node.dataset.total || "";
    }

    tree.querySelectorAll<HTMLElement>("li.chapter").forEach((chapter) => {
      const chapterMatch = text !== "" && (chapter.dataset.search || "").includes(text);
      let chapterVisible = 0;
      chapter.querySelectorAll<HTMLElement>(":scope > details > ul > li.block").forEach((block) => {
        const blockMatch = chapterMatch || (text !== "" && (block.dataset.search || "").includes(text));
        let visible = 0;
        const rubrics = block.querySelectorAll<HTMLElement>(":scope > details > ul > li.rubric");
        if (rubrics.length > 0) {
          rubrics.forEach((rubric) => {
            const rubricText = text !== "" && (rubric.dataset.search || "").includes(text);
            let rubricVisible = 0;
            let ownMatch = false;
            rubric.querySelectorAll<HTMLElement>(":scope > details > ul > li.doc").forEach((doc) => {
              const ageOk = age === "all" || doc.dataset.age === age;
              const docText = text !== "" && (doc.dataset.search || "").includes(text);
              if (docText) ownMatch = true;
              if (showDoc(doc, ageOk, text === "" || blockMatch || rubricText || docText)) rubricVisible += 1;
            });
            rubric.classList.toggle("is-hidden", rubricVisible === 0);
            setCount(rubric, rubricVisible);
            if (filtering && rubricVisible > 0 && text !== "" && (rubricText || ownMatch)) {
              const details = rubric.querySelector("details");
              if (details) details.open = true;
            }
            visible += rubricVisible;
          });
        } else {
          block.querySelectorAll<HTMLElement>(":scope > details > ul > li.doc").forEach((doc) => {
            const ageOk = age === "all" || doc.dataset.age === age;
            const textOk = text === "" || blockMatch || (doc.dataset.search || "").includes(text);
            if (showDoc(doc, ageOk, textOk)) visible += 1;
          });
        }
        block.classList.toggle("is-hidden", visible === 0);
        setCount(block, visible);
        if (filtering && visible > 0) {
          const details = block.querySelector("details");
          if (details) details.open = true;
        }
        chapterVisible += visible;
      });
      chapter.classList.toggle("is-hidden", chapterVisible === 0);
      setCount(chapter, chapterVisible);
      if (filtering && chapterVisible > 0) {
        const details = chapter.querySelector("details");
        if (details) details.open = true;
      }
      visibleDocs += chapterVisible;
    });

    if (!filtering && wasFiltering.current) showThreeLevels();
    wasFiltering.current = filtering;
    setShown(`Показано ${visibleDocs} из ${TOTAL}`);
    setEmpty(visibleDocs === 0);
  }, [query, age, treeHtml]);

  return (
    <div className="nosology">
      <div className="wrap">
        <p className="back"><Link href="/">← OKF Studio</Link></p>
        <h1>Классификатор клинических рекомендаций</h1>
        <p className="lead">Класс и блок выбираются по большинству кодов МКБ-10 документа. Коды вне выбранного класса в выборе блока не участвуют. Блок — конечный диапазон МКБ-10 внутри класса; если код не входит ни в один такой диапазон, блоком становится его трёхзначная рубрика. При равенстве предпочитается блок злокачественных новообразований (коды C), иначе блок первого кода. Внутри диапазона рекомендации собраны по трёхзначной рубрике.</p>
        <p className="meta">Срез 2026-11-26. Все 781 действующие рекомендации. У 125 есть коды и в других классах — они помечены «+».</p>
        <div className="stats">
          <div className="stat"><b>781</b><span>рекомендаций в дереве</span></div>
          <div className="stat"><b>22</b><span>классов МКБ-10</span></div>
          <div className="stat"><b>181</b><span>блоков внутри классов</span></div>
          <div className="stat"><b>{rubricCount}</b><span>трёхзначных рубрик</span></div>
        </div>
        <div className="toolbar">
          <input type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Класс, блок, рубрика, рекомендация, код МКБ-10 или ID" autoComplete="off" aria-label="Поиск" />
          <select value={age} onChange={(event) => setAge(event.target.value)} aria-label="Возраст">
            <option value="all">Все возраста</option>
            <option value="взрослые">Взрослые</option>
            <option value="дети">Дети</option>
            <option value="взрослые и дети">Взрослые и дети</option>
          </select>
          <button type="button" onClick={() => { setQuery(""); setAge("all"); showTwoLevels(); }}>Два</button>
          <button type="button" onClick={() => { setQuery(""); setAge("all"); showThreeLevels(); }}>Три</button>
          <button type="button" onClick={() => treeRef.current?.querySelectorAll("details").forEach((node) => { node.open = true; })}>Развернуть</button>
          <button type="button" onClick={() => treeRef.current?.querySelectorAll("details").forEach((node) => { node.open = false; })}>Свернуть</button>
        </div>
        <div className="legend">
          <span><i className="swatch adult" />Взрослые</span>
          <span><i className="swatch child" />Дети</span>
          <span><i className="swatch both" />Взрослые и дети</span>
        </div>
        <p className="shown">{shown}</p>
        <p className={`empty${empty ? " show" : ""}`}>Ничего не найдено.</p>
        <ul className="tree" ref={treeRef} dangerouslySetInnerHTML={{ __html: treeHtml }} />
      </div>
    </div>
  );
}
