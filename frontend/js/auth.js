// Auth logic
window.auth = {
  currentUser: null,
  
  init() {
    this.checkSession();
  },

  async checkSession() {
    try {
      const user = await window.api.fetch('/auth/me');
      this.loginSuccess(user);
    } catch (e) {
      this.handleUnauthorized();
    }
  },

  handleUnauthorized() {
    this.currentUser = null;
    this.showModal();
    document.getElementById('userInfo').style.display = 'none';
    document.getElementById('logoutBtn').style.display = 'none';
  },

  loginSuccess(user) {
    this.currentUser = user;
    this.hideModal();
    
    // Update topbar UI
    document.getElementById('userName').textContent = user.username;
    document.getElementById('userInfo').style.display = 'flex';
    document.getElementById('logoutBtn').style.display = 'block';
    
    // Trigger load of user specific data
    if (window.documentsAPI) window.documentsAPI.loadList();
    if (window.historyAPI) window.historyAPI.loadList();
  },

  async handleFormSubmit(e) {
    e.preventDefault();
    const errorBox = document.getElementById('authError');
    errorBox.textContent = '';
    
    const isLogin = document.getElementById('authLoginTab').classList.contains('active');
    const endpoint = isLogin ? '/auth/login' : '/auth/register';
    
    const data = {
      email: document.getElementById('authEmail').value.trim(),
      password: document.getElementById('authPassword').value
    };
    if (!isLogin) {
      data.username = document.getElementById('authUsername').value.trim();
    }

    try {
      const user = await window.api.fetch(endpoint, {
        method: 'POST',
        body: JSON.stringify(data)
      });
      this.loginSuccess(user);
    } catch (err) {
      errorBox.textContent = err.message;
    }
  },

  async logout() {
    try {
      await window.api.fetch('/auth/logout', { method: 'POST' });
    } finally {
      // Clear data locally
      window.location.reload();
    }
  },

  showModal() {
    document.getElementById('authModalBackdrop').classList.add('open');
  },
  
  hideModal() {
    document.getElementById('authModalBackdrop').classList.remove('open');
  },

  switchTab(tab) {
    const isLogin = tab === 'login';
    document.getElementById('authLoginTab').classList.toggle('active', isLogin);
    document.getElementById('authRegisterTab').classList.toggle('active', !isLogin);
    
    document.getElementById('authUsernameGroup').style.display = isLogin ? 'none' : 'block';
    document.getElementById('authUsername').required = !isLogin;
    
    document.getElementById('authSubmitBtn').textContent = isLogin ? 'Войти' : 'Зарегистрироваться';
    document.getElementById('authError').textContent = '';
  }
};
