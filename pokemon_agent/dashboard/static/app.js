/* ============================================
   Hermes Plays Pokémon — Dashboard Client
   Pure vanilla JS, no frameworks
   ============================================ */

(function () {
    'use strict';

    // --- Constants ---
    const BADGE_NAMES = ['Boulder', 'Cascade', 'Thunder', 'Rainbow', 'Soul', 'Marsh', 'Volcano', 'Earth'];
    const TYPE_COLORS = {
        Normal: '#A8A878', Fire: '#F08030', Water: '#6890F0', Grass: '#78C850',
        Electric: '#F8D030', Ice: '#98D8D8', Fighting: '#C03028', Poison: '#A040A0',
        Ground: '#E0C068', Flying: '#A890F0', Psychic: '#F85888', Bug: '#A8B820',
        Rock: '#B8A038', Ghost: '#705898', Dragon: '#7038F8', Dark: '#705848',
        Steel: '#B8B8D0', Fairy: '#EE99AC'
    };
    const POLL_INTERVAL = 3000;
    const WS_RECONNECT_BASE = 1000;
    const WS_RECONNECT_MAX = 30000;

    // --- State ---
    let ws = null;
    let wsConnected = false;
    let wsReconnectDelay = WS_RECONNECT_BASE;
    let wsReconnectTimer = null;
    let pollTimer = null;
    let screenshotTimer = null;
    let autoScroll = true;
    let turnCount = 0;
    let lastStateJSON = '';
    let hasReceivedFrame = false;

    // --- DOM refs ---
    const $ = (id) => document.getElementById(id);
    const statusDot = $('statusDot');
    const statusText = $('statusText');
    const logContainer = $('logContainer');
    const gameScreen = $('gameScreen');
    const screenOverlay = $('screenOverlay');
    const teamContainer = $('teamContainer');
    const badgesRow = $('badgesRow');
    const statMap = $('statMap');
    const statPosition = $('statPosition');
    const statMoney = $('statMoney');
    const statPlayTime = $('statPlayTime');
    const statTurns = $('statTurns');
    const battleInfo = $('battleInfo');
    const battleContent = $('battleContent');
    const dialogOverlay = $('dialogOverlay');
    const dialogText = $('dialogText');
    const frameCount = $('frameCount');
    const btnClearLog = $('btnClearLog');

    // --- Utilities ---
    function getBaseURL() {
        return window.location.protocol + '//' + window.location.host;
    }

    function getWSURL() {
        var proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        return proto + '//' + window.location.host + '/ws';
    }

    function timeNow() {
        var d = new Date();
        return pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds());
    }

    function pad(n) {
        return n < 10 ? '0' + n : '' + n;
    }

    function formatPlayTime(pt) {
        if (!pt) return '--:--:--';
        return pad(pt.hours || 0) + ':' + pad(pt.minutes || 0) + ':' + pad(pt.seconds || 0);
    }

    // --- Connection Status ---
    function setStatus(connected, text) {
        if (connected) {
            statusDot.classList.add('connected');
        } else {
            statusDot.classList.remove('connected');
        }
        statusText.textContent = text || (connected ? 'Connected' : 'Disconnected');
    }

    // --- Logging ---
    function addLog(type, text) {
        var entry = document.createElement('div');
        entry.className = 'log-entry log-' + type;

        var timeSpan = document.createElement('span');
        timeSpan.className = 'log-time';
        timeSpan.textContent = timeNow();

        var textSpan = document.createElement('span');
        textSpan.className = 'log-text';
        textSpan.textContent = text;

        entry.appendChild(timeSpan);
        entry.appendChild(textSpan);
        logContainer.appendChild(entry);

        // Limit log entries to prevent memory issues
        while (logContainer.children.length > 500) {
            logContainer.removeChild(logContainer.firstChild);
        }

        if (autoScroll) {
            logContainer.scrollTop = logContainer.scrollHeight;
        }
    }

    function renderLog(event) {
        if (!event) return;
        var type = event.type || 'status';
        // Server broadcasts fields at top level (not nested under .data),
        // but some event formats use .data — check both.
        var data = event.data || event;

        switch (type) {
            case 'action':
                var actions = data.actions || event.actions || [];
                var actionText = Array.isArray(actions) && actions.length
                    ? actions.join(', ')
                    : (data.action || '(unknown)');
                addLog('action', '▶ ' + actionText);
                turnCount++;
                statTurns.textContent = turnCount;
                break;
            case 'reasoning':
                addLog('thinking', '💭 ' + (data.text || event.text || ''));
                break;
            case 'tool_call':
                addLog('system', '⚙ ' + (data.tool || data.name || event.tool || '') + (data.args ? ' → ' + JSON.stringify(data.args) : ''));
                break;
            case 'tool_result':
                addLog('system', '← ' + truncate(data.result || event.result || JSON.stringify(data), 200));
                break;
            case 'error':
                addLog('error', '✕ ' + (data.message || data.error || event.error || JSON.stringify(data)));
                break;
            case 'key_moment':
                addLog('key-moment', '★ ' + (data.description || event.description || JSON.stringify(data)));
                break;
            case 'battle':
                addLog('action', '⚔ Battle vs ' + (data.opponent || event.opponent || '???') + ': ' + (data.result || event.result || ''));
                break;
            case 'state_update':
                // silent - handled by renderStats
                break;
            case 'screenshot':
                // silent - handled by renderGameScreen
                break;
            default:
                addLog('status', (data.message || data.text || event.message || event.text || JSON.stringify(event)));
                break;
        }
    }

    function truncate(s, max) {
        if (typeof s !== 'string') s = JSON.stringify(s);
        return s.length > max ? s.substring(0, max) + '...' : s;
    }

    // --- Game Screen ---
    function renderGameScreen(base64png) {
        if (!base64png) return;
        if (!hasReceivedFrame) {
            hasReceivedFrame = true;
            screenOverlay.classList.add('hidden');
        }
        gameScreen.src = 'data:image/png;base64,' + base64png;
    }

    // --- Stats ---
    function renderStats(state) {
        if (!state) return;
        var player = state.player;
        var mapInfo = state.map || {};
        if (player) {
            var pos = player.position || {};
            statMap.textContent = mapInfo.map_name || 'Unknown';
            statPosition.textContent = '(' + (pos.x != null ? pos.x : '--') + ', ' + (pos.y != null ? pos.y : '--') + ')';
            statMoney.textContent = '$' + (player.money != null ? player.money.toLocaleString() : '---');
            // play_time can be a string "H:MM:SS" or an object {hours, minutes, seconds}
            var pt = player.play_time;
            if (typeof pt === 'string') {
                statPlayTime.textContent = pt;
            } else {
                statPlayTime.textContent = formatPlayTime(pt);
            }
            renderBadges(player.badge_count, player.badges);
        }

        // Dialog
        var dialog = state.dialog;
        if (dialog && dialog.active && dialog.text) {
            dialogOverlay.classList.remove('hidden');
            dialogText.textContent = dialog.text;
        } else {
            dialogOverlay.classList.add('hidden');
        }

        // Battle
        if (state.battle) {
            renderBattle(state.battle);
        } else {
            battleInfo.classList.add('hidden');
        }

        // Party
        if (state.party) {
            renderTeam(state.party);
        }

        // Frame count
        if (state.metadata && state.metadata.frame_count) {
            frameCount.textContent = 'Frame ' + state.metadata.frame_count;
        }
    }

    // --- Badges ---
    function renderBadges(badgeCount, badgesList) {
        var circles = badgesRow.children;
        var earned = badgesList || [];
        for (var i = 0; i < 8; i++) {
            var el = circles[i];
            if (!el) continue;
            var has = false;
            if (typeof badgeCount === 'number') {
                has = i < badgeCount;
            }
            if (earned.indexOf(BADGE_NAMES[i]) !== -1) {
                has = true;
            }
            el.textContent = has ? '●' : '○';
            el.title = BADGE_NAMES[i] + (has ? ' ✓' : '');
            if (has) {
                el.classList.add('earned');
            } else {
                el.classList.remove('earned');
            }
        }
    }

    // --- Team ---
    function renderTeam(party) {
        teamContainer.innerHTML = '';
        for (var i = 0; i < 6; i++) {
            if (i < party.length) {
                teamContainer.appendChild(createTeamCard(party[i]));
            } else {
                teamContainer.appendChild(createEmptyCard());
            }
        }
    }

    function createTeamCard(mon) {
        var card = document.createElement('div');
        card.className = 'team-card';

        // Name
        var name = document.createElement('div');
        name.className = 'team-name';
        name.textContent = mon.nickname || mon.species || '???';
        card.appendChild(name);

        // Level
        var level = document.createElement('div');
        level.className = 'team-level';
        level.textContent = 'Lv.' + (mon.level || '?');
        card.appendChild(level);

        // Types
        if (mon.types && mon.types.length) {
            var types = document.createElement('div');
            types.className = 'team-types';
            for (var t = 0; t < mon.types.length; t++) {
                var badge = document.createElement('span');
                badge.className = 'type-badge';
                badge.textContent = mon.types[t];
                badge.style.backgroundColor = TYPE_COLORS[mon.types[t]] || '#888';
                types.appendChild(badge);
            }
            card.appendChild(types);
        }

        // HP bar
        var hp = mon.hp != null ? mon.hp : 0;
        var maxHp = mon.max_hp || 1;
        var pct = Math.round((hp / maxHp) * 100);

        var hpContainer = document.createElement('div');
        hpContainer.className = 'hp-bar-container';

        var hpBar = document.createElement('div');
        hpBar.className = 'hp-bar';

        var hpFill = document.createElement('div');
        hpFill.className = 'hp-bar-fill';
        if (pct > 50) hpFill.classList.add('hp-high');
        else if (pct > 20) hpFill.classList.add('hp-mid');
        else hpFill.classList.add('hp-low');
        hpFill.style.width = pct + '%';

        hpBar.appendChild(hpFill);
        hpContainer.appendChild(hpBar);

        var hpText = document.createElement('span');
        hpText.className = 'hp-text';
        hpText.textContent = hp + '/' + maxHp;
        hpContainer.appendChild(hpText);

        card.appendChild(hpContainer);

        // Status condition
        if (mon.status) {
            var statusEl = document.createElement('span');
            statusEl.className = 'status-condition ' + mon.status.toLowerCase();
            statusEl.textContent = mon.status.toUpperCase();
            card.appendChild(statusEl);
        }

        // Moves
        if (mon.moves && mon.moves.length) {
            var moves = document.createElement('div');
            moves.className = 'team-moves';
            moves.textContent = mon.moves.join(' / ');
            card.appendChild(moves);
        }

        return card;
    }

    function createEmptyCard() {
        var card = document.createElement('div');
        card.className = 'team-card empty-card';
        var name = document.createElement('div');
        name.className = 'team-name';
        name.textContent = 'Empty';
        card.appendChild(name);
        var ball = document.createElement('div');
        ball.className = 'empty-pokeball';
        ball.textContent = '○';
        card.appendChild(ball);
        return card;
    }

    // --- Battle ---
    function renderBattle(battle) {
        battleInfo.classList.remove('hidden');
        battleContent.innerHTML = '';

        var enemy = battle.enemy || {};
        var playerMon = battle.player_pokemon || {};

        var info = document.createElement('div');
        info.innerHTML = '';

        // Battle type
        var typeLabel = document.createElement('span');
        typeLabel.className = 'type-badge';
        typeLabel.textContent = (battle.type || 'wild').toUpperCase();
        typeLabel.style.backgroundColor = battle.type === 'trainer' ? '#C03028' : '#58a6ff';
        info.appendChild(typeLabel);

        // Enemy info
        var enemyText = document.createElement('span');
        enemyText.textContent = '  vs ' + (enemy.species || '???') + ' Lv.' + (enemy.level || '?');
        info.appendChild(enemyText);

        // Enemy HP
        if (enemy.hp_percent != null) {
            var enemyHpBar = document.createElement('div');
            enemyHpBar.className = 'hp-bar';
            enemyHpBar.style.width = '80px';
            enemyHpBar.style.display = 'inline-block';
            enemyHpBar.style.verticalAlign = 'middle';
            enemyHpBar.style.marginLeft = '8px';

            var enemyFill = document.createElement('div');
            enemyFill.className = 'hp-bar-fill';
            var ep = enemy.hp_percent;
            if (ep > 50) enemyFill.classList.add('hp-high');
            else if (ep > 20) enemyFill.classList.add('hp-mid');
            else enemyFill.classList.add('hp-low');
            enemyFill.style.width = ep + '%';
            enemyHpBar.appendChild(enemyFill);
            info.appendChild(enemyHpBar);
        }

        battleContent.appendChild(info);
    }

    // --- WebSocket ---
    function connectWS() {
        if (ws && (ws.readyState === WebSocket.CONNECTING || ws.readyState === WebSocket.OPEN)) {
            return;
        }

        var url = getWSURL();
        try {
            ws = new WebSocket(url);
        } catch (e) {
            scheduleReconnect();
            return;
        }

        ws.onopen = function () {
            wsConnected = true;
            wsReconnectDelay = WS_RECONNECT_BASE;
            setStatus(true, '⚡ Connected (WS)');
            addLog('status', 'WebSocket connected');
            // Keep polling for screenshots since WS may not send them
        };

        ws.onmessage = function (evt) {
            try {
                var msg = JSON.parse(evt.data);
                handleWSMessage(msg);
            } catch (e) {
                // ignore parse errors
            }
        };

        ws.onclose = function () {
            wsConnected = false;
            setStatus(false, 'Disconnected');
            scheduleReconnect();
        };

        ws.onerror = function () {
            // onclose will fire after this
        };
    }

    function scheduleReconnect() {
        if (wsReconnectTimer) return;
        wsReconnectTimer = setTimeout(function () {
            wsReconnectTimer = null;
            connectWS();
        }, wsReconnectDelay);
        wsReconnectDelay = Math.min(wsReconnectDelay * 2, WS_RECONNECT_MAX);
    }

    function handleWSMessage(msg) {
        var type = msg.type || msg.event;

        // Extract state from whichever field the server uses
        var statePayload = msg.data || msg.state || msg.state_after || null;

        if (type === 'action') {
            // Action events: log the action and update state
            renderLog(msg);
            if (msg.state_after) {
                var stateJSON = JSON.stringify(msg.state_after);
                if (stateJSON !== lastStateJSON) {
                    lastStateJSON = stateJSON;
                    renderStats(msg.state_after);
                }
            }
        } else if (type === 'state_update' && statePayload) {
            var stateJSON = JSON.stringify(statePayload);
            if (stateJSON !== lastStateJSON) {
                lastStateJSON = stateJSON;
                renderStats(statePayload);
            }
        } else if (type === 'screenshot' && msg.data && msg.data.image) {
            renderGameScreen(msg.data.image);
        } else {
            renderLog(msg);
        }
    }

    // --- Polling ---
    function pollState() {
        fetch(getBaseURL() + '/state')
            .then(function (r) {
                if (!r.ok) throw new Error('HTTP ' + r.status);
                return r.json();
            })
            .then(function (state) {
                if (!wsConnected) {
                    setStatus(true, '● Connected (polling)');
                }
                var stateJSON = JSON.stringify(state);
                if (stateJSON !== lastStateJSON) {
                    lastStateJSON = stateJSON;
                    renderStats(state);
                }
            })
            .catch(function (e) {
                if (!wsConnected) {
                    setStatus(false, 'Server unreachable');
                }
            });
    }

    function pollScreenshot() {
        fetch(getBaseURL() + '/screenshot/base64')
            .then(function (r) {
                if (!r.ok) throw new Error('HTTP ' + r.status);
                return r.json();
            })
            .then(function (data) {
                if (data && data.image) {
                    renderGameScreen(data.image);
                }
            })
            .catch(function () {
                // silent fail
            });
    }

    function startPolling() {
        // Always poll for state and screenshots
        pollState();
        pollScreenshot();
        pollTimer = setInterval(pollState, POLL_INTERVAL);
        screenshotTimer = setInterval(pollScreenshot, POLL_INTERVAL);
    }

    // --- Auto-scroll ---
    logContainer.addEventListener('scroll', function () {
        var threshold = 40;
        var atBottom = (logContainer.scrollHeight - logContainer.scrollTop - logContainer.clientHeight) < threshold;
        autoScroll = atBottom;
    });

    // --- Clear log ---
    btnClearLog.addEventListener('click', function () {
        logContainer.innerHTML = '';
        addLog('status', 'Log cleared');
    });

    // --- Corner bracket decorations (bottom corners) ---
    function addBottomCorners() {
        var frame = document.querySelector('.game-screen-frame');
        if (!frame) return;
        var bl = document.createElement('div');
        bl.className = 'corner-bl';
        var br = document.createElement('div');
        br.className = 'corner-br';
        frame.appendChild(bl);
        frame.appendChild(br);
    }

    // --- Health check on startup ---
    function checkHealth() {
        fetch(getBaseURL() + '/health')
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (data.status === 'ok') {
                    addLog('status', 'Server is running');
                    if (data.game) {
                        addLog('status', 'Game: ' + data.game);
                    }
                }
            })
            .catch(function () {
                addLog('error', 'Cannot reach server at ' + getBaseURL());
            });
    }

    // --- Init ---
    function init() {
        addBottomCorners();
        setStatus(false, 'Connecting...');
        addLog('status', 'Hermes Plays Pokémon Dashboard loaded');
        addLog('status', 'Connecting to server...');

        checkHealth();
        connectWS();
        startPolling();
    }

    // Wait for DOM
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

})();
