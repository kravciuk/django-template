import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { Header } from "@/components/Header";
import { HomeContent } from "@/components/HomeContent";
import "@/index.css";
import { type HeaderData, type HomeData, readJson } from "@/types";

// Two independent mount points, one bundle (see templates/base.html /
// content/home.html): #header-root is present on every page, #home-root
// only on the home page. Each hydrates from its own json_script payload.

const headerRoot = document.getElementById("header-root");
if (headerRoot) {
  const headerData = readJson<HeaderData>("header-data");
  if (headerData) {
    createRoot(headerRoot).render(
      <StrictMode>
        <Header data={headerData} />
      </StrictMode>,
    );
  }
}

const homeRoot = document.getElementById("home-root");
if (homeRoot) {
  const homeData = readJson<HomeData>("home-data");
  if (homeData) {
    createRoot(homeRoot).render(
      <StrictMode>
        <HomeContent data={homeData} />
      </StrictMode>,
    );
  }
}
