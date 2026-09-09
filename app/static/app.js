const $ = id => document.getElementById(id);
let users = [], roundId = null, busy = false;

function screen(name) {
  for (const id of ['setup', 'loading', 'pick', 'empty']) $(id).hidden = id !== name;
}
function error(message = '') {
  $('error').textContent = message;
  $('error').hidden = !message;
}
async function api(path, body) {
  const response = await fetch(path, body === undefined ? {} : {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)
  });
  const data = await response.json().catch(() => ({error: 'The server could not complete the request. Please try again.'}));
  if (!response.ok) throw new Error([data.error || 'Something went wrong.', ...(data.warnings || [])].join(' '));
  return data;
}
function roster() {
  $('users').replaceChildren();
  users.forEach(user => {
    const li = document.createElement('li');
    const name = document.createElement('span'); name.textContent = '@' + user;
    const remove = document.createElement('button');
    remove.textContent = '×'; remove.setAttribute('aria-label', 'Remove ' + user);
    remove.onclick = () => { users = users.filter(u => u !== user); roster(); };
    li.append(name, remove); $('users').append(li);
  });
  $('start').disabled = users.length === 0;
}
$('add-form').onsubmit = event => {
  event.preventDefault(); error();
  const user = $('username').value.trim().replace(/^https?:\/\/(www\.)?letterboxd\.com\//i, '').replace(/^[@/]+|\/+$/g, '').toLowerCase();
  if (!/^[a-z0-9_][a-z0-9_-]{0,63}$/.test(user)) return error('Enter a Letterboxd username or profile URL.');
  if (users.length >= 30) return error('You can add up to 30 users.');
  if (!users.includes(user)) users.push(user);
  $('username').value = ''; roster(); $('username').focus();
};
function showFilm(film) {
  if (!film) { screen('empty'); return; }
  $('title').textContent = film.title;
  $('fallback-title').textContent = film.title;
  $('poster').hidden = true; $('poster-fallback').hidden = false;
  $('poster').onload = () => { $('poster').hidden = false; $('poster-fallback').hidden = true; };
  $('poster').onerror = () => { $('poster').hidden = true; $('poster-fallback').hidden = false; };
  $('poster').removeAttribute('src');
  $('poster').alt = film.title + ' poster';
  if (film.poster) $('poster').src = film.poster;
  $('metadata').textContent = [film.year, film.rating ? `★ ${film.rating} / ${film.rating_scale} on Letterboxd` : null].filter(Boolean).join('  ·  ');
  $('tagline').textContent = film.tagline || '';
  $('description').textContent = film.description || 'A little mystery never hurt a movie night. See Letterboxd for the full story.';
  $('owners').textContent = 'On the watchlist of ' + film.owners.map(u => '@' + u).join(', ');
  $('odds').textContent = `${film.remaining} unique films · ${film.entries} weighted entries in this draw`;
  $('film-link').href = film.url;
  screen('pick');
}
async function run(task) {
  if (busy) return;
  busy = true; error();
  document.querySelectorAll('button').forEach(button => button.disabled = true);
  try { await task(); } catch (err) { error(err.message || 'Network error. Check your connection and try again.'); }
  finally { busy = false; document.querySelectorAll('button').forEach(button => button.disabled = false); $('start').disabled = !users.length; }
}
$('start').onclick = () => run(async () => {
  screen('loading'); $('loading-title').textContent = 'Raiding the watchlists…';
  try {
    const data = await api('/api/rounds', {users, refresh: $('refresh').checked, repeats: $('repeats').checked});
    roundId = data.id;
    $('warnings').textContent = data.warnings.join(' '); $('warnings').hidden = !data.warnings.length;
    showFilm(data.film);
  } catch (err) { screen('setup'); throw err; }
});
$('reroll').onclick = () => run(async () => {
  $('reroll').textContent = 'Finding another…';
  try { showFilm((await api(`/api/rounds/${roundId}/reroll`, {})).film); }
  finally { $('reroll').textContent = '↻ Pick again'; }
});
$('lock').onclick = () => run(async () => {
  const data = await api(`/api/rounds/${roundId}/lock`, {});
  $('pick').classList.add('locked');
  $('pick-actions').hidden = true; $('celebration').hidden = false;
  $('pick-eyebrow').textContent = "TONIGHT'S MAIN EVENT";
  $('enjoy').textContent = `Enjoy ${data.film.title}!`;
  $('restart').hidden = true;
});
function restart() {
  if (busy) return;
  roundId = null; error(); screen('setup');
  $('pick').classList.remove('locked'); $('pick-actions').hidden = false;
  $('celebration').hidden = true; $('restart').hidden = false;
  $('pick-eyebrow').textContent = 'FATE HAS GOOD TASTE';
}
for (const id of ['restart', 'restart-locked', 'restart-empty']) $(id).onclick = restart;
run(async () => { users = (await api('/api/config')).users; roster(); });
