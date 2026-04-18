// Central API configuration and request wrapper
const API_BASE = '/api/v1';

class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

async function apiFetch(endpoint, options = {}) {
  const defaultHeaders = {
    'Accept': 'application/json',
  };
  
  if (!(options.body instanceof FormData)) {
    defaultHeaders['Content-Type'] = 'application/json';
  }

  const config = {
    ...options,
    headers: {
      ...defaultHeaders,
      ...options.headers,
    },
  };

  try {
    const response = await fetch(`${API_BASE}${endpoint}`, config);
    
    // Auth token expired / not logged in
    if (response.status === 401 && window.auth) {
      window.auth.handleUnauthorized();
    }

    if (!response.ok) {
      let errorMessage = 'Ошибка сервера';
      try {
        const errData = await response.json();
        errorMessage = errData.detail || errorMessage;
      } catch (e) {
        const txt = await response.text();
        if (txt) errorMessage = txt;
      }
      throw new ApiError(errorMessage, response.status);
    }

    // 204 No Content
    if (response.status === 204) return null;
    
    return await response.json();
  } catch (error) {
    if (error instanceof ApiError) throw error;
    throw new Error('Сетевая ошибка или сервер недоступен');
  }
}

window.api = { fetch: apiFetch };
