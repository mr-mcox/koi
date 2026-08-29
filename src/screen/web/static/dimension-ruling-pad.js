// Delegated click handler for the dimension-ruling 2D pad (dimension-ruling bearing).
// Delegated on `document`, not the pad itself, because HTMX swaps `#rating-content`
// (including any pad inside it) on every submit — a directly-attached listener would be
// lost on the first click. One click sets both fit (x) and settledness (y) and submits;
// the form's hidden `mean`/`settledness` inputs are what the server actually reads.
document.addEventListener("click", function (event) {
  const pad = event.target.closest(".dimension-ruling-pad");
  if (!pad) return;

  const rect = pad.getBoundingClientRect();
  const x = Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width));
  const y = Math.min(1, Math.max(0, (event.clientY - rect.top) / rect.height));
  const mean = (x * 2 - 1).toFixed(2);
  const settledness = (1 - y).toFixed(2);

  const form = pad.closest("form");
  form.querySelector('input[name="mean"]').value = mean;
  form.querySelector('input[name="settledness"]').value = settledness;
  form.requestSubmit();
});
