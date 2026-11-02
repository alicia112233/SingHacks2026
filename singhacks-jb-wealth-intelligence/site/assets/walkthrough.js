(function () {
  'use strict';

  // Wires: [id, fromBox, toBox, kind]. Shapes are computed from box positions.
  var WIRES = [
    ['w-yahoo', 'src-yahoo', 'packet', 'pub'], ['w-cnbc', 'src-cnbc', 'packet', 'pub'],
    ['w-bt', 'src-bt', 'packet', 'pub'], ['w-gnews', 'src-gnews', 'packet', 'pub'], ['w-bank', 'src-bank', 'packet', 'pub'],
    ['w-gpt', 'packet', 'm-gpt', 'pub'], ['w-claude', 'packet', 'm-claude', 'pub'], ['w-gemini', 'packet', 'm-gemini', 'pub'],
    ['wv-gpt', 'm-gpt', 'vote', 'pub'], ['wv-claude', 'm-claude', 'vote', 'pub'], ['wv-gemini', 'm-gemini', 'vote', 'pub'],
    ['w-in', 'vote', 'engine', 'bank'], ['w-port', 'portfolio', 'engine', 'bank'], ['w-score', 'engine', 'score', 'bank'],
    ['w-review', 'engine', 'inhouse', 'bank'], ['w-rm', 'inhouse', 'rm', 'bank'], ['w-ledger', 'rm', 'ledger', 'bank']
  ];
  var TO_MODELS = ['w-gpt', 'w-claude', 'w-gemini'];
  var VOTES = ['wv-gpt', 'wv-claude', 'wv-gemini'];

  var COLORS = { goal: 'var(--green)', liq: 'var(--slate)', rules: 'var(--gold)', time: '#7E9C8F', fit: 'var(--line-2)', news: 'var(--red)' };
  var LABELS = { goal: 'Goal clash', liq: 'Liquidity', rules: 'Rules', time: 'Time', fit: 'Fit', news: 'News' };

  var SCEN = {
    abdullah: {
      client: {
        name: 'Abdullah Al-Mansoori', meta: 'USD 32.2m · Hong Kong · Balanced Growth',
        goal: '“Build wealth outside the Gulf and outside shipping.”',
        holdings: [['Fixed Coupon Note, Basket C (looked through)', 4.16, 1], ['Pacific Orient Shipping Ltd', 3.68, 1],
          ['Global Energy Majors Equity Fund', 2.88, 1], ['Asia Pacific Shipping and Logistics Fund', 2.86, 1],
          ['Global Developed Equity Index Fund', 4.28, 0], ['Other holdings', 14.34, 0]],
        sum: '42.1% of his portfolio is shipping and energy'
      },
      src: 'src-bt',
      headline: 'AI outlook, energy prices to drive Asian markets as Fed holds rate steady',
      hmeta: 'The Business Times · 29 Oct 2026 · sent: headline, publisher, date',
      votes: { gpt: 'energy, rates · Medium', claude: 'energy, rates · Medium', gemini: 'energy · High' },
      tally: ['Topics: energy, rates', 'majority vote · median severity Medium · illustrative'],
      before: { goal: 40, liq: 0, rules: 0, time: 7, fit: 3, news: 0 }, news: 5,
      laneBefore: 'week', laneAfter: 'week',
      review: { title: 'Ring-fence the family-office seed capital', code: 65, angles: [['Suitability and compliance', 78], ['Client fit', 74], ['Evidence quality', 82]] },
      rm: { choices: ['Approve', 'Edit', 'Dismiss'], pick: 'Approve', note: 'Example note: agreed a dated funding sleeve for the USD 5m family-office seed.' },
      record: 'CL-0019 · approved · Ring-fence the family-office seed capital',
      steps: [
        { s: 'GET 3 RSS feeds + 1 search feed · 1 new headline', t: 'A headline lands from a public feed.', d: 'The Business Times reports energy prices driving Asian markets. Feeds are public data (C1 to C2). A bank could add its own market reviews as one more feed.', on: ['src-bt', 'packet'], w: ['w-bt'], st: { src: 1, packet: 1 } },
        { s: 'POST headline, publisher, date → 3 outside models', t: 'Only the headline leaves the bank. No client goes with it.', d: 'Three outside models each get the headline text, publisher and date. Nothing about any client, portfolio or RM is sent.', on: ['packet', 'm-gpt', 'm-claude', 'm-gemini'], w: TO_MODELS, st: {} },
        { s: 'votes in · topics energy, rates · severity Medium', t: 'The models vote on what the headline is about and how serious it is.', d: 'Topics go by majority vote, severity by the median. If no model answers, fixed keyword rules decide instead.', on: ['m-gpt', 'm-claude', 'm-gemini', 'vote'], w: VOTES, st: { votes: 1, tally: 1 } },
        { s: 'inside the bank · matching topics against 20 portfolios', t: 'Inside the bank, code matches the topics to what each client holds.', d: 'Energy touches Abdullah. Looking through his structured note, 42.1% of his portfolio is shipping and energy: the bet he asked to move away from, and the same industry as the business he owns.', on: ['vote', 'engine', 'portfolio'], w: ['w-in', 'w-port'], st: { e: 1, hits: 1 } },
        { s: 'recalculating urgency · news +5 · 50 → 55', t: 'His urgency score moves from 50 to 55.', d: 'From his own record: goal clash 40, time 7, fit +3. The news adds 5 of a possible 8. He stays in This week: the clash is serious, but nothing is due today.', on: ['engine', 'score'], w: ['w-score'], st: { e: 2, after: 1 } },
        { s: 'in-house model · 3 angles · consensus 65', t: 'The bank’s own model reviews the action code proposes.', d: 'Code proposes ring-fencing the USD 5m family-office seed, scored 65. The in-house model checks it from three angles. The result is the lower of the code’s score and the angles’ median, so the model can only lower confidence.', on: ['engine', 'inhouse'], w: ['w-review'], st: { e: 3, review: 1 } },
        { s: 'brief ready · RM approves with a note', t: 'The RM decides.', d: 'The RM sees the evidence and a brief: open with his goal, show the look-through, never predict when the Strait reopens. Approving needs a note saying what was done.', on: ['inhouse', 'rm'], w: ['w-rm'], st: { rm: 1 } },
        { s: 'ledger += 1 record · append-only', t: 'The decision is recorded, never overwritten.', d: 'Client, action, decision, note, who and when. A change of mind is a new record, so compliance can replay exactly what happened.', on: ['rm', 'ledger'], w: ['w-ledger'], st: { ledger: 1 } }
      ]
    },
    ravi: {
      client: {
        name: 'Ravi Chandrasekaran', meta: 'USD 46.7m · Singapore · Growth · loan at 73.7% LTV, call at 75%',
        goal: 'Bridge liquidity until his founder-share sale, then diversify.',
        holdings: [['Aranya Technologies (unlisted)', 31.92, 1], ['US Technology Leaders Fund', 3.55, 1],
          ['Helios Cloud Systems, stock and note', 3.64, 1], ['Meridian Semiconductor Corp', 2.24, 1], ['Other holdings', 5.35, 0]],
        sum: '91.2% touched · pledged holdings back his loan'
      },
      src: 'src-gnews',
      headline: 'Today’s Market Recap: Fed Holds Rates Steady, Memory Chip Sector Surges, Micron Up Over 5%, SanDisk Up Over 7%, Google Drops Nearly 10% After Hours',
      hmeta: 'TradingKey via Google News · 29 Oct 2026 · sent: headline, publisher, date',
      votes: { gpt: 'technology, rates · High', claude: 'technology, rates · High', gemini: 'technology · High' },
      tally: ['Topics: technology, rates', 'majority vote · median severity High · illustrative'],
      before: { goal: 40, liq: 2, rules: 13, time: 8, fit: 2, news: 0 }, news: 5,
      laneBefore: 'week', laneAfter: 'exposed',
      flag: 'Touches holdings pledged for his loan, 1.3 points from its margin call. Illustrative stress: lending value −4.5% against a 1.7% cushion. Not a forecast.',
      review: null,
      rm: { choices: ['Confirm', 'Dismiss'], pick: 'Confirm', note: 'What to check: collateral value and loan headroom before the next client call.' },
      record: 'CL-0002 · exposure confirmed · market recap, 29 Oct',
      steps: [
        { s: 'GET 3 RSS feeds + 1 search feed · 1 new headline', t: 'A market recap lands from a public search feed.', d: 'Chip stocks surged and Google fell nearly 10% after hours. Public data (C1 to C2), picked up by a Google News search the bank configures.', on: ['src-gnews', 'packet'], w: ['w-gnews'], st: { src: 1, packet: 1 } },
        { s: 'POST headline, publisher, date → 3 outside models', t: 'Only the headline leaves the bank.', d: 'The outside models never learn that a client called Ravi exists, let alone what he holds or owes.', on: ['packet', 'm-gpt', 'm-claude', 'm-gemini'], w: TO_MODELS, st: {} },
        { s: 'votes in · topics technology, rates · severity High', t: 'The models agree: technology and rates, high severity.', d: 'Topics by majority vote, severity by the median of the three.', on: ['m-gpt', 'm-claude', 'm-gemini', 'vote'], w: VOTES, st: { votes: 1, tally: 1 } },
        { s: 'inside the bank · 91.2% of holdings touched', t: 'Inside the bank, code finds the headline touches almost everything he holds.', d: 'Technology covers 91.2% of Ravi’s portfolio after looking through funds and notes. Several of those holdings are pledged against his loan.', on: ['vote', 'engine', 'portfolio'], w: ['w-in', 'w-port'], st: { e: 1, hits: 1 } },
        { s: 'urgency 65 → 70 · flag: may be exposed', t: 'He jumps to the top of the queue, flagged “May be exposed”.', d: 'His score moves from 65 to 70, into Act now. Separately, the exposure flag puts him first whatever the score, because the loan is already close to a margin call. TESSERA says what to check, not what the market will do.', on: ['engine', 'score'], w: ['w-score'], st: { e: 2, after: 1 } },
        { s: 'flag → RM · what to check: collateral, headroom', t: 'The RM checks, then confirms or dismisses the flag.', d: 'No action is proposed yet, so there is nothing for the in-house model to review. The RM checks collateral value and loan headroom before calling the client.', on: ['rm'], w: [], st: { rm: 1, skipReview: 1 } },
        { s: 'ledger += 1 record · append-only', t: 'The RM’s call is recorded.', d: 'Confirmed or dismissed, with who and when. If the RM dismisses it, the reason stays on record too.', on: ['rm', 'ledger'], w: ['w-ledger'], st: { ledger: 1 } }
      ]
    }
  };

  var $ = function (id) { return document.getElementById(id); };
  var stage = $('stage'), wires = $('wires');
  var scen = 'abdullah', step = 0, playing = false, timer = null, typeTimer = null, raf = null;
  var paths = {};

  // ---- layout -------------------------------------------------------------
  function box(id) { var e = $(id); return { x: e.offsetLeft, y: e.offsetTop, w: e.offsetWidth, h: e.offsetHeight }; }
  function shape(id, a, b) {
    var A = box(a), B = box(b), cx = function (r) { return r.x + r.w / 2; }, cy = function (r) { return r.y + r.h / 2; };
    if (a.indexOf('src-') === 0) return 'M' + cx(A) + ' ' + (A.y + A.h) + ' L' + cx(A) + ' ' + B.y;
    if (TO_MODELS.indexOf(id) >= 0) {
      // A bus at y=100 between the model row and the tally, then up into each model.
      var sx = A.x + A.w, sy = cy(A), x = cx(B) - 18, bus = 100;
      return 'M' + sx + ' ' + sy + ' C' + (sx + 24) + ' ' + sy + ' ' + (sx + 14) + ' ' + bus + ' ' + (sx + 40) + ' ' + bus +
        ' L' + (x - 8) + ' ' + bus + ' Q' + x + ' ' + bus + ' ' + x + ' ' + (bus - 8) + ' L' + x + ' ' + (B.y + B.h);
    }
    if (VOTES.indexOf(id) >= 0) return 'M' + (cx(A) + 18) + ' ' + (A.y + A.h) + ' L' + (cx(A) + 18) + ' ' + B.y;
    if (id === 'w-in') { var x1 = cx(A), y1 = A.y + A.h, x2 = B.x + B.w - 60, y2 = B.y; return 'M' + x1 + ' ' + y1 + ' C' + x1 + ' ' + (y1 + 50) + ' ' + x2 + ' ' + (y2 - 50) + ' ' + x2 + ' ' + y2; }
    if (id === 'w-port') return 'M' + (A.x + A.w) + ' ' + (B.y + 60) + ' L' + B.x + ' ' + (B.y + 60);
    if (id === 'w-review') return 'M' + (A.x + 105) + ' ' + (A.y + A.h) + ' L' + (A.x + 105) + ' ' + B.y;
    return 'M' + (A.x + A.w) + ' ' + cy(B) + ' L' + B.x + ' ' + cy(B);
  }
  function drawWires() {
    wires.innerHTML = '';
    WIRES.forEach(function (w) {
      var p = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      p.setAttribute('d', shape(w[0], w[1], w[2]));
      p.setAttribute('class', 'wire' + (w[3] === 'pub' ? ' pub' : ''));
      p.id = w[0];
      wires.appendChild(p);
      paths[w[0]] = p;
    });
  }
  function fit() {
    var holder = stage.parentElement, avail = holder.parentElement.clientWidth - 2;
    var s = Math.max(0.62, Math.min(1, avail / 1120));
    stage.style.transform = 'scale(' + s + ')';
    holder.style.width = Math.round(1120 * s) + 'px';
    holder.style.height = Math.round(660 * s) + 'px';
  }

  // ---- rendering ----------------------------------------------------------
  function sum(o) { return o.goal + o.liq + o.rules + o.time + o.fit + o.news; }
  function laneHTML(l) {
    return l === 'exposed' ? '<span class="lane exposed">May be exposed</span>' : l === 'now' ? '<span class="lane now">Act now</span>' : '<span class="lane week">This week</span>';
  }
  function state(k) {
    var st = {};
    SCEN[scen].steps.slice(0, k + 1).forEach(function (x) { for (var key in x.st) st[key] = x.st[key]; });
    return st;
  }
  function render() {
    var S = SCEN[scen], st = state(step), cur = S.steps[step];

    document.querySelectorAll('.box').forEach(function (b) { b.classList.toggle('on', cur.on.indexOf(b.id) >= 0); b.classList.remove('dim'); });
    document.querySelectorAll('.src').forEach(function (b) { if (st.src && b.id !== S.src) b.classList.add('dim'); });
    Object.keys(paths).forEach(function (id) {
      var on = cur.w.indexOf(id) >= 0;
      paths[id].classList.toggle('on', on);
      paths[id].classList.toggle('alert', on && scen === 'ravi' && (id === 'w-score' || id === 'w-port'));
    });

    var pk = $('packet');
    pk.classList.toggle('show', !!st.packet);
    pk.innerHTML = '<span class="ph">' + S.headline + '</span><span class="pm">' + S.hmeta + '</span>';

    ['gpt', 'claude', 'gemini'].forEach(function (m) {
      $('v-' + m).textContent = st.votes ? S.votes[m] : 'waiting';
      $('m-' + m).classList.toggle('voted', !!st.votes);
    });
    var vt = $('vote');
    vt.classList.toggle('show', !!st.tally);
    vt.innerHTML = '<span class="ph">' + S.tally[0] + '</span><span class="pm">' + S.tally[1] + '</span>';

    var c = S.client, total = c.holdings.reduce(function (a, h) { return a + h[1]; }, 0), max = Math.max.apply(null, c.holdings.map(function (h) { return h[1]; }));
    $('portfolio').innerHTML = '<p class="bx-k">Client record · stays here</p><h3>' + c.name + '</h3><p class="meta">' + c.meta + '</p><p class="goal">' + c.goal + '</p>' +
      c.holdings.map(function (h) {
        return '<div class="hold' + (st.hits && h[2] ? ' hit' : '') + '"><span class="nm">' + h[0] + '</span><span class="vl">' + h[1].toFixed(2) + '</span><span class="bar"><i style="width:' + (h[1] / max * 100).toFixed(1) + '%"></i></span></div>';
      }).join('') + '<p class="sum' + (st.hits ? ' show' : '') + '">' + c.sum + '</p>';
    void total;

    ['e1', 'e2', 'e3'].forEach(function (id, i) {
      var li = $(id), n = st.e || 0;
      li.className = i + 1 < n ? 'done' : i + 1 === n ? 'run' : '';
      if (scen === 'ravi' && id === 'e3' && n >= 2) li.textContent = 'Flag possible exposure';
      else if (id === 'e3') li.textContent = 'Propose an action';
    });
    if (step === S.steps.length - 1) ['e1', 'e2', 'e3'].forEach(function (id) { if ($(id).className === 'run') $(id).className = 'done'; });

    var parts = Object.assign({}, S.before, st.after ? { news: S.news } : {}), sc = sum(parts);
    var lane = st.after ? S.laneAfter : S.laneBefore;
    var scale = 99;
    $('score').innerHTML = '<p class="bx-k">Urgency score · out of 99</p><div class="row"><span class="num" id="num">' + sc + '<small> / 99</small></span>' + laneHTML(lane) + '</div>' +
      '<div class="stack">' + Object.keys(COLORS).map(function (k) { return '<i style="width:' + (Math.max(parts[k], 0) / scale * 100).toFixed(2) + '%;background:' + COLORS[k] + '" title="' + LABELS[k] + ' ' + parts[k] + '"></i>'; }).join('') + '</div>' +
      '<div class="legend">' + Object.keys(COLORS).filter(function (k) { return parts[k]; }).map(function (k) { return '<span style="--c:' + COLORS[k] + '">' + LABELS[k] + ' ' + (k === 'fit' && parts[k] > 0 ? '+' : '') + parts[k] + '</span>'; }).join('') + '</div>' +
      (st.after && S.flag ? '<p class="flagnote">' + S.flag + '</p>' : '');

    var ih = $('inhouse');
    if (S.review && st.review) {
      var sorted = S.review.angles.map(function (a) { return a[1]; }).sort(function (a, b) { return a - b; }), med = sorted[1];
      ih.innerHTML = '<p class="bx-k">In-house model · offline</p><small>' + S.review.title + '</small><div class="angles">' +
        S.review.angles.map(function (a) { return '<div class="angle"><span>' + a[0].split(' ')[0] + '</span><span>' + a[1] + '</span></div>'; }).join('') +
        '</div><p class="consensus">min(code ' + S.review.code + ', median ' + med + ') = ' + Math.min(S.review.code, med) + '</p>';
    } else if (st.skipReview) {
      ih.innerHTML = '<p class="bx-k">In-house model · offline</p><small>Not needed yet. A flag asks the RM to check first; actions are reviewed once one is proposed.</small>';
      ih.classList.add('dim');
    } else {
      ih.innerHTML = '<p class="bx-k">In-house model · offline</p><small>Reviews each proposed action from three angles. Sees client data, never leaves the bank.</small>';
    }

    $('rm').innerHTML = '<p class="bx-k">Relationship manager</p><b>Priscilla Ong</b><small>synthetic RM</small><div class="choices">' +
      S.rm.choices.map(function (ch) { return '<span' + (st.rm && ch === S.rm.pick ? ' class="pick"' : '') + '>' + ch + '</span>'; }).join('') + '</div>' +
      (st.rm ? '<p class="note">' + S.rm.note + '</p>' : '');

    $('ledger').innerHTML = '<p class="bx-k">Decision ledger · append-only</p><div class="rows">' +
      (st.ledger ? '<p class="new">' + S.record + '</p>' : '') + '<p>… earlier records</p></div>';

    $('step-of').textContent = 'Step ' + (step + 1) + ' of ' + S.steps.length;
    $('cap-title').textContent = cur.t;
    $('cap-detail').textContent = cur.d;
    $('steps').innerHTML = S.steps.map(function (_, i) {
      return '<button type="button" data-i="' + i + '"' + (i === step ? ' aria-current="step"' : '') + (i < step ? ' class="past"' : '') + ' aria-label="Step ' + (i + 1) + '">' + (i + 1) + '</button>';
    }).join('');

    $('t-prev').textContent = step > 0 ? S.steps[step - 1].s : '';
    type(cur.s);
    animateDots(cur.w);
  }

  function type(text) {
    clearInterval(typeTimer);
    var el = $('t-now'), i = 0;
    if (matchMedia('(prefers-reduced-motion: reduce)').matches) { el.textContent = text; return; }
    el.textContent = '';
    typeTimer = setInterval(function () { el.textContent = text.slice(0, ++i); if (i >= text.length) clearInterval(typeTimer); }, 18);
  }

  function animateDots(ids) {
    cancelAnimationFrame(raf);
    wires.querySelectorAll('circle').forEach(function (c) { c.remove(); });
    if (!ids.length || matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    var dots = ids.map(function (id) {
      var c = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
      var kind = paths[id].classList.contains('alert') ? 'alert' : paths[id].classList.contains('pub') ? 'pub' : '';
      c.setAttribute('r', '6'); c.setAttribute('class', 'dot ' + kind);
      wires.appendChild(c);
      return { c: c, p: paths[id], len: paths[id].getTotalLength() };
    });
    var t0 = performance.now();
    (function frame(now) {
      var t = ((now - t0) % 1700) / 1300;
      dots.forEach(function (d) {
        var u = Math.min(t, 1), pt = d.p.getPointAtLength(d.len * (u < .5 ? 2 * u * u : 1 - Math.pow(-2 * u + 2, 2) / 2));
        d.c.setAttribute('cx', pt.x); d.c.setAttribute('cy', pt.y); d.c.style.opacity = t > 1 ? 0 : 1;
      });
      raf = requestAnimationFrame(frame);
    })(t0);
  }

  // ---- controls -----------------------------------------------------------
  function go(i) { var n = SCEN[scen].steps.length; step = Math.max(0, Math.min(n - 1, i)); render(); }
  function setPlaying(p) {
    playing = p;
    clearTimeout(timer);
    $('play-label').textContent = p ? 'pause' : 'play';
    $('play').setAttribute('aria-label', p ? 'Pause' : 'Play');
    $('play-icon').setAttribute('d', p ? 'M3 1.5 H6 V12.5 H3 Z M8 1.5 H11 V12.5 H8 Z' : 'M3 1.5 L12 7 L3 12.5 Z');
    if (p) tick();
  }
  function tick() {
    timer = setTimeout(function () {
      if (step >= SCEN[scen].steps.length - 1) { setPlaying(false); return; }
      go(step + 1); tick();
    }, 4200);
  }
  function pick(name) {
    scen = name;
    document.querySelectorAll('.scen button').forEach(function (b) { b.setAttribute('aria-selected', String(b.dataset.scen === name)); });
    setPlaying(false); go(0);
  }

  $('play').addEventListener('click', function () {
    if (!playing && step >= SCEN[scen].steps.length - 1) go(0);
    setPlaying(!playing);
  });
  $('restart').addEventListener('click', function () { setPlaying(false); go(0); });
  $('steps').addEventListener('click', function (e) { var b = e.target.closest('button'); if (b) { setPlaying(false); go(+b.dataset.i); } });
  document.querySelectorAll('.scen button').forEach(function (b) { b.addEventListener('click', function () { pick(b.dataset.scen); }); });
  document.addEventListener('keydown', function (e) {
    if (e.target.closest('input, textarea')) return;
    if (e.key === 'ArrowRight') { setPlaying(false); go(step + 1); }
    else if (e.key === 'ArrowLeft') { setPlaying(false); go(step - 1); }
    else if (e.key === ' ' && !e.target.closest('button')) { e.preventDefault(); $('play').click(); }
    else if (e.key === 'r' || e.key === 'R') { setPlaying(false); go(0); }
  });

  // Wrap the stage in a sizer so scaling also shrinks its layout box.
  var sizer = document.createElement('div');
  sizer.style.overflow = 'hidden';
  stage.parentElement.insertBefore(sizer, stage);
  sizer.appendChild(stage);
  window.addEventListener('resize', fit);

  if (location.hash === '#ravi') scen = 'ravi';
  fit(); drawWires();
  pick(scen);
})();
