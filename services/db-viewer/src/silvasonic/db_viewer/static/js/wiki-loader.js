/**
 * Silvasonic — Wikipedia Species Loader
 *
 * Fetches a Wikipedia summary for a species and renders it into the page.
 *
 * Usage: Add this script tag and set data-species on #wiki-content:
 *   <div id="wiki-content" data-species="Parus major">Loading...</div>
 *   <a id="wiki-link" href="#" class="hidden">Read more</a>
 *   <script src="/static/js/wiki-loader.js"></script>
 */
document.addEventListener("DOMContentLoaded", () => {
    const wikiContentDiv = document.getElementById("wiki-content");
    const wikiLink = document.getElementById("wiki-link");

    if (!wikiContentDiv) return;

    const speciesName = wikiContentDiv.dataset.species;
    if (!speciesName) {
        wikiContentDiv.innerHTML = '<p class="text-base-content/50">No species name provided.</p>';
        return;
    }

    const wikiTitle = speciesName.replace(/ /g, "_");

    fetch(`https://en.wikipedia.org/api/rest_v1/page/summary/${wikiTitle}`)
        .then(response => {
            if (!response.ok) throw new Error("Wikipedia API error");
            return response.json();
        })
        .then(data => {
            if (data.extract_html) {
                wikiContentDiv.innerHTML = data.extract_html;
                if (wikiLink && data.desktop && data.desktop.page) {
                    wikiLink.href = data.desktop.page;
                    wikiLink.classList.remove("hidden");
                }
            } else {
                throw new Error("No abstract found");
            }
        })
        .catch(err => {
            console.error("Failed to load Wikipedia data:", err);
            wikiContentDiv.innerHTML = `<p class="text-error">Could not load Wikipedia information.</p>`;
        });
});
