#!/usr/bin/node
/* Small Node HTTP/CGI bridge for webOS firmware without BusyBox httpd. */
'use strict';

var http = require('http');
var fs = require('fs');
var path = require('path');
var url = require('url');
var childProcess = require('child_process');

var port = parseInt(process.argv[2], 10);
var webRoot = path.resolve(process.argv[3] || '/var/lib/webosbrew/panelcomfort/www');
var rootDir = '/var/lib/webosbrew/panelcomfort';
var maxBodyBytes = 8192;
var maxCgiOutputBytes = 1024 * 1024;
var maxConcurrentCgi = 4;
var maxQueuedCgi = 96;
var activeCgi = 0;
var queuedCgi = [];
var mimeTypes = {
  '.html': 'text/html; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.js': 'application/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.ico': 'image/x-icon'
};

function send(res, code, body, contentType) {
  if (res.finished) return;
  res.writeHead(code, {
    'Content-Type': contentType || 'text/plain; charset=utf-8',
    'Cache-Control': 'no-store',
    'X-Content-Type-Options': 'nosniff',
    'Content-Length': Buffer.byteLength(body)
  });
  res.end(body);
}

function remoteAddress(req) {
  var address = (req.socket && req.socket.remoteAddress) ||
    (req.connection && req.connection.remoteAddress) || '';
  if (address.indexOf('::ffff:') === 0) address = address.substring(7);
  if (address === '::1') address = '127.0.0.1';
  return address;
}

function isPrivateIpv4(address) {
  var parts = address.split('.');
  if (parts.length !== 4) return false;
  for (var i = 0; i < 4; i++) {
    if (!/^\d{1,3}$/.test(parts[i]) || Number(parts[i]) > 255) return false;
  }
  var a = Number(parts[0]);
  var b = Number(parts[1]);
  return a === 10 || a === 127 || (a === 192 && b === 168) ||
    (a === 172 && b >= 16 && b <= 31);
}

function cgiPath(pathname) {
  var fixed = {
    '/cgi-bin/index.cgi': 'index.cgi',
    '/cgi-bin/panelcomfort-health.cgi': 'panelcomfort-health.cgi',
    '/cgi-bin/panelcomfort-discovery.cgi': 'panelcomfort-discovery.cgi',
    '/cgi-bin/panelcomfort-ha.cgi': 'panelcomfort-ha.cgi',
    '/cgi-bin/panelcomfort-web.cgi': 'panelcomfort-web.cgi'
  };
  var file = fixed[pathname];
  var webhook = /^\/cgi-bin\/pc-([a-fA-F0-9]{8})$/.exec(pathname);
  if (!file && webhook) file = 'pc-' + webhook[1];
  if (!file) return null;
  return path.join(webRoot, 'cgi-bin', file);
}

function runCgi(req, res, requestUrl, pathname, script, body, onFinished) {
  var env = {};
  Object.keys(process.env).forEach(function (key) { env[key] = process.env[key]; });
  env.GATEWAY_INTERFACE = 'CGI/1.1';
  env.REQUEST_METHOD = req.method;
  env.QUERY_STRING = requestUrl.query || '';
  env.CONTENT_LENGTH = String(body.length);
  env.CONTENT_TYPE = req.headers['content-type'] || '';
  env.REMOTE_ADDR = remoteAddress(req);
  env.SERVER_NAME = (req.headers.host || '').split(':')[0];
  env.SERVER_PORT = String(port);
  env.SERVER_PROTOCOL = 'HTTP/' + (req.httpVersion || '1.1');
  env.SCRIPT_NAME = pathname;
  env.SCRIPT_FILENAME = script;
  env.HTTP_HOST = req.headers.host || '';
  env.HTTP_ORIGIN = req.headers.origin || '';
  env.HTTP_USER_AGENT = req.headers['user-agent'] || '';
  env.HTTP_ACCEPT = req.headers.accept || '';

  var proc;
  var chunks = [];
  var total = 0;
  var completed = false;
  var slotReleased = false;
  function releaseSlot() {
    if (slotReleased) return;
    slotReleased = true;
    onFinished();
  }
  function internalError(message) {
    if (completed) return;
    completed = true;
    console.error('[PanelComfort] CGI handler failed: ' + message);
    send(res, 502, 'CGI handler failed\n');
    releaseSlot();
  }

  try {
    proc = childProcess.spawn('/bin/sh', [script], { env: env, stdio: ['pipe', 'pipe', 'pipe'] });
  } catch (error) {
    internalError(error.message || 'could not start shell');
    return;
  }
  proc.on('error', function (error) { internalError(error.message || 'could not start shell'); });
  proc.stdout.on('data', function (chunk) {
    total += chunk.length;
    if (total > maxCgiOutputBytes) {
      proc.kill();
      internalError('response exceeded size limit');
      return;
    }
    chunks.push(chunk);
  });
  proc.stderr.on('data', function (chunk) {
    var message = chunk.toString('utf8').replace(/[\r\n]+/g, ' ').substring(0, 500);
    if (message) console.error('[PanelComfort] CGI: ' + message);
  });
  proc.on('close', function () {
    if (completed) return;
    completed = true;
    var output = Buffer.concat(chunks);
    var text = output.toString('binary');
    var split = text.indexOf('\r\n\r\n');
    var separatorLength = 4;
    if (split < 0) {
      split = text.indexOf('\n\n');
      separatorLength = 2;
    }
    if (split < 0) {
      send(res, 502, 'CGI handler returned an invalid response\n');
      releaseSlot();
      return;
    }
    var headerText = text.substring(0, split);
    var responseBody = output.slice(split + separatorLength);
    var status = 200;
    var responseHeaders = {
      'Cache-Control': 'no-store',
      'X-Content-Type-Options': 'nosniff'
    };
    headerText.split(/\r?\n/).forEach(function (line) {
      var colon = line.indexOf(':');
      if (colon < 1) return;
      var name = line.substring(0, colon).trim().toLowerCase();
      var value = line.substring(colon + 1).trim();
      if (name === 'status') {
        var match = /^(\d{3})/.exec(value);
        if (match) status = Number(match[1]);
      } else if (name === 'content-type') {
        responseHeaders['Content-Type'] = value;
      } else if (name === 'cache-control') {
        responseHeaders['Cache-Control'] = value;
      } else if (name === 'x-content-type-options') {
        responseHeaders['X-Content-Type-Options'] = value;
      } else if (name === 'location') {
        responseHeaders.Location = value;
      }
    });
    responseHeaders['Content-Length'] = responseBody.length;
    if (!res.finished) {
      res.writeHead(status, responseHeaders);
      res.end(responseBody);
    }
    releaseSlot();
  });
  res.on('close', function () {
    if (!res.finished && proc) proc.kill();
  });
  proc.stdin.end(body);
}

function pumpCgiQueue() {
  while (activeCgi < maxConcurrentCgi && queuedCgi.length) {
    var job = queuedCgi.shift();
    if (job.res.finished) continue;
    activeCgi++;
    runCgi(job.req, job.res, job.requestUrl, job.pathname, job.script, job.body, function () {
      activeCgi--;
      pumpCgiQueue();
    });
  }
}

function queueCgi(req, res, requestUrl, pathname, script, body) {
  var job = { req: req, res: res, requestUrl: requestUrl, pathname: pathname, script: script, body: body };
  if (activeCgi < maxConcurrentCgi) {
    activeCgi++;
    runCgi(req, res, requestUrl, pathname, script, body, function () {
      activeCgi--;
      pumpCgiQueue();
    });
    return;
  }
  if (queuedCgi.length >= maxQueuedCgi) {
    send(res, 503, 'PanelComfort is busy; retry shortly\n');
    return;
  }
  queuedCgi.push(job);
}

function serveStatic(req, res, pathname) {
  if (pathname.indexOf('/cgi-bin/') === 0) {
    send(res, 404, 'Not found\n');
    return;
  }
  var decoded;
  try { decoded = decodeURIComponent(pathname); }
  catch (error) { send(res, 400, 'Bad request\n'); return; }
  if (decoded.indexOf('\0') >= 0 || decoded.indexOf('\\') >= 0) {
    send(res, 400, 'Bad request\n');
    return;
  }
  if (decoded === '/') decoded = '/index.html';
  var filename = path.resolve(webRoot, '.' + decoded);
  if (filename !== webRoot && filename.indexOf(webRoot + path.sep) !== 0) {
    send(res, 403, 'Forbidden\n');
    return;
  }
  fs.stat(filename, function (error, stat) {
    if (error || !stat.isFile()) { send(res, 404, 'Not found\n'); return; }
    fs.readFile(filename, function (readError, contents) {
      if (readError) { send(res, 500, 'Could not read file\n'); return; }
      var type = mimeTypes[path.extname(filename).toLowerCase()] || 'application/octet-stream';
      if (req.method === 'HEAD') {
        res.writeHead(200, {
          'Content-Type': type,
          'Cache-Control': 'no-store',
          'X-Content-Type-Options': 'nosniff',
          'Content-Length': contents.length
        });
        res.end();
      } else {
        res.writeHead(200, {
          'Content-Type': type,
          'Cache-Control': 'no-store',
          'X-Content-Type-Options': 'nosniff',
          'Content-Length': contents.length
        });
        res.end(contents);
      }
    });
  });
}

var server = http.createServer(function (req, res) {
  var requestUrl = url.parse(req.url || '/');
  var pathname = requestUrl.pathname || '/';
  var remote = remoteAddress(req);
  if (!isPrivateIpv4(remote)) { send(res, 403, 'Private IPv4 client required\n'); return; }
  if (req.method !== 'GET' && req.method !== 'HEAD' && req.method !== 'POST') {
    send(res, 405, 'Method not allowed\n');
    return;
  }
  var script = req.method === 'HEAD' ? null : cgiPath(pathname);
  if (script) {
    if (req.method !== 'GET' && req.method !== 'POST') { send(res, 405, 'Method not allowed\n'); return; }
    if (!fs.existsSync(script)) { send(res, 404, 'Not found\n'); return; }
    var bodyChunks = [];
    var bodySize = 0;
    var tooLarge = false;
    req.on('data', function (chunk) {
      if (tooLarge) return;
      bodySize += chunk.length;
      if (bodySize > maxBodyBytes) {
        tooLarge = true;
        send(res, 413, 'Request too large\n');
        return;
      }
      bodyChunks.push(chunk);
    });
    req.on('end', function () {
      if (tooLarge || res.finished) return;
      queueCgi(req, res, requestUrl, pathname, script, Buffer.concat(bodyChunks));
    });
    return;
  }
  if (pathname.indexOf('/cgi-bin/') === 0) { send(res, 404, 'Not found\n'); return; }
  if (req.method === 'POST') { send(res, 405, 'Method not allowed\n'); return; }
  serveStatic(req, res, pathname);
});

server.on('clientError', function (_error, socket) {
  socket.end('HTTP/1.1 400 Bad Request\r\nConnection: close\r\n\r\n');
});
server.on('error', function (error) {
  console.error('[PanelComfort] HTTP listener failed: ' + (error.message || error));
  process.exit(1);
});
server.listen(port, '0.0.0.0', function () {
  console.log('[PanelComfort] HTTP listener running on 0.0.0.0:' + port);
});
