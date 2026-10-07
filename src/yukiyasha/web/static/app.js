const statusEl = document.querySelector("#status");
const runtimeState = document.querySelector("#runtime-state");
const versionEl = document.querySelector("#version");
const environmentEl = document.querySelector("#environment");
const telemetry = document.querySelector("#telemetry");

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

document.querySelector("#refresh").addEventListener("click", refreshRuntime);
document.querySelector("#inspect").addEventListener("click", refreshRuntime);
refreshRuntime();
