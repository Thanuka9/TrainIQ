/**
 * TrainIQ AI helpers — streaming SSE, job polling, canvas vision capture.
 */
window.TrainIQAI = (function () {
  'use strict';

  function captureCanvas(canvas, quality, maxWidth) {
    if (!canvas || !canvas.toDataURL) return null;
    try {
      quality = quality || 0.72;
      maxWidth = maxWidth || 960;
      let src = canvas;
      let w = canvas.width;
      let h = canvas.height;
      if (w > maxWidth) {
        const ratio = maxWidth / w;
        w = maxWidth;
        h = Math.round(canvas.height * ratio);
        const tmp = document.createElement('canvas');
        tmp.width = w;
        tmp.height = h;
        tmp.getContext('2d').drawImage(canvas, 0, 0, w, h);
        src = tmp;
      }
      const dataUrl = src.toDataURL('image/jpeg', quality);
      return dataUrl.split(',')[1] || null;
    } catch (_) {
      return null;
    }
  }

  async function streamPost(url, body, headers, onChunk) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 180000);
    try {
      const res = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...headers },
        body: JSON.stringify(body),
        signal: controller.signal,
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.error || err.message || `Request failed (${res.status})`);
      }
      if (!res.body) {
        throw new Error('Streaming not supported by browser');
      }
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      let meta = {};

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';
        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          try {
            const data = JSON.parse(line.slice(6));
            if (data.error) throw new Error(data.error);
            if (data.text) onChunk(data.text, data);
            if (data.done) meta = data;
          } catch (e) {
            if (e.message && !String(e.message).includes('JSON')) throw e;
          }
        }
      }
      return meta;
    } catch (e) {
      if (e.name === 'AbortError') {
        throw new Error('AI request timed out. Try again or use a shorter page.');
      }
      if (e.message === 'Failed to fetch') {
        throw new Error('Could not reach the AI service. Check that Ollama is running and refresh the page.');
      }
      throw e;
    } finally {
      clearTimeout(timer);
    }
  }

  async function postJson(url, body, headers) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 120000);
    try {
      const res = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...headers },
        body: JSON.stringify(body),
        signal: controller.signal,
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`);
      return data;
    } catch (e) {
      if (e.name === 'AbortError') {
        throw new Error('AI request timed out. Try again.');
      }
      if (e.message === 'Failed to fetch') {
        throw new Error('Could not reach the AI service. Check that Ollama is running.');
      }
      throw e;
    } finally {
      clearTimeout(timer);
    }
  }

  function pollJob(jobId, onUpdate, intervalMs) {
    intervalMs = intervalMs || 2000;
    return new Promise((resolve, reject) => {
      const tick = async () => {
        try {
          const res = await fetch(`/ai/jobs/${jobId}`);
          const job = await res.json();
          if (!res.ok) throw new Error(job.error || 'Job poll failed');
          onUpdate && onUpdate(job);
          if (job.status === 'complete') return resolve(job.result);
          if (job.status === 'failed') return reject(new Error(job.error || 'Job failed'));
          setTimeout(tick, intervalMs);
        } catch (e) {
          reject(e);
        }
      };
      tick();
    });
  }

  function applyCreatorOutline(outline) {
    sessionStorage.setItem('creatoriq_outline', JSON.stringify(outline));
    window.location.href = '/study_materials/upload_course?creatoriq=1';
  }

  return { streamPost, postJson, pollJob, captureCanvas, applyCreatorOutline };
})();
