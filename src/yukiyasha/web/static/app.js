const statusEl = document.querySelector("#status");
const runtimeState = document.querySelector("#runtime-state");
const versionEl = document.querySelector("#version");
const environmentEl = document.querySelector("#environment");
const telemetry = document.querySelector("#telemetry");
const projectList = document.querySelector("#project-list");
const projectPath = document.querySelector("#project-path");
const projectCount = document.querySelector("#project-count");
const workspaceTitle = document.querySelector("#workspace-title");

let activeProjectPath = "projects/work";

const projectNames = {
  "projects/work": "Рабочие проекты",
  "projects/home": "Домашние проекты",
};

async function refreshRuntime() {
  telemetry.textContent = "Запрос к ядру…";

  try {
    const response = await fetch("/api/runtime", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);

    const data = await response.json();
    runtimeState.textContent = data.state;
    versionEl.textContent = `v${data.version}`;
    environmentEl.textContent = data.environment;
    telemetry.textContent = JSON.stringify(data, null, 2);

    statusEl.classList.add("online");
    statusEl.querySelector("span").textContent = "Ядро активно";
  } catch (error) {
    statusEl.classList.remove("online");
    statusEl.querySelector("span").textContent = "Нет связи";
    telemetry.textContent = `Ошибка: ${error.message}`;
  }
}

async function refreshProjects() {
  projectList.innerHTML = '<div class="empty-state">Загрузка…</div>';
  projectPath.textContent = activeProjectPath;
  workspaceTitle.textContent = projectNames[activeProjectPath];

  try {
    const response = await fetch(
      `/api/disk?path=${encodeURIComponent(activeProjectPath)}`,
      { cache: "no-store" },
    );
    if (!response.ok) throw new Error(`HTTP ${response.status}`);

    const data = await response.json();
    const entries = data.entries;
    projectCount.textContent = `${entries.length} объектов`;

    if (!entries.length) {
      projectList.innerHTML = '<div class="empty-state">Здесь пока нет файлов.</div>';
      return;
    }

    projectList.replaceChildren(
      ...entries.map((entry) => {
        const row = document.createElement("div");
        row.className = "project-row";

        const icon = document.createElement("span");
        icon.className = "kind";
        icon.textContent = entry.type === "directory" ? "▣" : "•";

        const name = document.createElement("strong");
        name.textContent = entry.name;

        const meta = document.createElement("small");
        meta.textContent = entry.type === "directory" ? "папка" : `${entry.size} байт`;

        row.append(icon, name, meta);
        return row;
      }),
    );
  } catch (error) {
    projectCount.textContent = "ошибка";
    projectList.innerHTML = '<div class="empty-state">Не удалось открыть раздел.</div>';
  }
}

document.querySelector("#refresh").addEventListener("click", refreshRuntime);
document.querySelector("#refresh-projects").addEventListener("click", refreshProjects);

document.querySelectorAll(".menu-item").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll(".menu-item").forEach((item) => item.classList.remove("active"));
    button.classList.add("active");
    activeProjectPath = button.dataset.projectPath;
    refreshProjects();
  });
});

refreshRuntime();
refreshProjects();
