/**
 * Multi-Tenant & Authenticated Frontend Client for Aero Productivity & Operations Agent.
 * Handles JWT/Bearer tokens, user profiles, tenant context, and real-time operations widgets.
 */

let currentTenantId = localStorage.getItem("aero_active_tenant") || "acme-electronics";
let authToken = localStorage.getItem("aero_auth_token") || null;
let currentUser = null;
let conversationHistory = [];
let salesChartInstance = null;
let allTenantsCache = [];

document.addEventListener("DOMContentLoaded", () => {
    initTheme();
    setupEventListeners();
    setupAuthListeners();
    setupSpeechRecognition();
    setupFloatingAgentWidget();

    // Async data loading in background
    fetchTenants();
    checkAuthStatus();
});

function initTheme() {
    const savedTheme = localStorage.getItem("aero_theme");
    if (savedTheme === "light") {
        document.body.classList.add("light-theme");
    }
}

function openFloatingAgent() {
    const floatCard = document.getElementById("aeroFloatCard");
    const unreadBadge = document.getElementById("floatUnreadBadge");
    const floatInput = document.getElementById("floatUserInput");
    if (floatCard) {
        floatCard.style.display = "flex";
        if (unreadBadge) unreadBadge.style.display = "none";
        const floatBadge = document.getElementById("floatTenantBadge");
        if (floatBadge) floatBadge.textContent = currentTenantId;
        setTimeout(() => {
            if (floatInput) floatInput.focus();
            const fContainer = document.getElementById("floatChatMessages");
            if (fContainer) fContainer.scrollTop = fContainer.scrollHeight;
        }, 50);
    }
}

function focusChatInput() {
    openFloatingAgent();
}

// Global Command Palette Shortcut (Ctrl+K or Cmd+K)
document.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        openFloatingAgent();
        showToast("Aero Operations Agent opened", "⚡");
    }
});

function showToast(message, icon = "⚡") {
    const container = document.getElementById("toastContainer");
    if (!container) return;
    const toast = document.createElement("div");
    toast.className = "toast";
    toast.innerHTML = `<span>${icon}</span> <span>${message}</span>`;
    container.appendChild(toast);
    setTimeout(() => {
        toast.style.opacity = "0";
        setTimeout(() => toast.remove(), 300);
    }, 3500);
}

// ----------------- Authentication & View State Management ----------------- //

async function checkAuthStatus() {
    if (!authToken) {
        showAuthGate();
        return;
    }

    try {
        const res = await fetch("/api/auth/me", {
            headers: { "Authorization": `Bearer ${authToken}` }
        });
        if (res.ok) {
            currentUser = await res.json();
            showDashboard(currentUser);
        } else {
            // Token expired or invalid
            logoutUser(false);
        }
    } catch (e) {
        console.error("Auth check failed", e);
        showAuthGate();
    }
}

function showDashboard(user) {
    currentUser = user;
    currentTenantId = user.tenant_id || currentTenantId;
    localStorage.setItem("aero_active_tenant", currentTenantId);

    // Toggle main view containers
    const gate = document.getElementById("authGateScreen");
    const workspace = document.getElementById("appWorkspace");
    if (gate) {
        gate.classList.add("hidden");
        gate.style.display = "none";
    }
    if (workspace) {
        workspace.classList.remove("hidden");
        workspace.style.display = "flex";
        workspace.style.flexDirection = "";
    }

    // Restore sidebar collapsed preference
    const isSidebarCollapsed = localStorage.getItem("aero_sidebar_collapsed") === "true";
    const sidebar = document.getElementById("saasSidebar");
    if (sidebar && isSidebarCollapsed) {
        sidebar.classList.add("collapsed");
    }

    updateUserAuthUI(user);

    // Sync tenant selector
    const sel = document.getElementById("tenantSelect");
    if (sel && sel.value !== currentTenantId) {
        sel.value = currentTenantId;
    }

    refreshAllTenantData();
}

function showAuthGate() {
    currentUser = null;
    const gate = document.getElementById("authGateScreen");
    const workspace = document.getElementById("appWorkspace");
    if (workspace) {
        workspace.classList.add("hidden");
        workspace.style.display = "none";
    }
    if (gate) {
        gate.classList.remove("hidden");
        gate.style.display = "flex";
        gate.style.flexDirection = "column";
    }

    // Reset password field
    const pwdInput = document.getElementById("gateLoginPassword");
    if (pwdInput) pwdInput.value = "";

    // Reset tabs to Sign In view
    const gateTabLogin = document.getElementById("gateTabLogin");
    const gateTabReg = document.getElementById("gateTabRegister");
    const gateFormLogin = document.getElementById("gateLoginForm");
    const gateFormReg = document.getElementById("gateRegisterForm");
    if (gateTabLogin && gateTabReg) {
        gateTabLogin.classList.add("active");
        gateTabReg.classList.remove("active");
    }
    if (gateFormLogin) gateFormLogin.style.display = "flex";
    if (gateFormReg) gateFormReg.style.display = "none";

    // Populate gate register tenant select
    populateGateTenantSelect();
}

function populateGateTenantSelect() {
    const sel = document.getElementById("gateRegTenantSelect");
    if (!sel || !allTenantsCache.length) return;
    sel.innerHTML = allTenantsCache.map(t => `<option value="${t.tenant_id}">${t.name} (${t.tenant_id})</option>`).join("");
}

function updateUserAuthUI(user) {
    const wrap = document.getElementById("userAuthWrap");
    if (wrap) {
        if (user) {
            wrap.innerHTML = `
                <div class="user-nav-chip">
                    <div class="user-chip-avatar">${user.full_name ? user.full_name.split(" ").map(n => n[0]).join("").toUpperCase().slice(0, 2) : "OP"}</div>
                    <div class="user-chip-info">
                        <span class="user-chip-name">${user.full_name}</span>
                        <span class="user-chip-role">${user.role}</span>
                    </div>
                    <button class="btn-user-signout" onclick="window.logoutUser(true)" title="Sign out of current account">
                        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"></path><polyline points="16 17 21 12 16 7"></polyline><line x1="21" y1="12" x2="9" y2="12"></line></svg>
                    </button>
                </div>
            `;
        } else {
            wrap.innerHTML = ``;
        }
    }

    // Update Sidebar User Profile Card
    const sideUserName = document.getElementById("sideUserName");
    const sideUserRole = document.getElementById("sideUserRole");
    const sideUserAvatar = document.getElementById("sideUserAvatar");
    if (user) {
        if (sideUserName) sideUserName.textContent = user.full_name;
        if (sideUserRole) sideUserRole.textContent = `${user.role} • ${user.email}`;
        if (sideUserAvatar) {
            const initials = user.full_name ? user.full_name.split(" ").map(n => n[0]).join("").toUpperCase().slice(0, 2) : "OP";
            sideUserAvatar.textContent = initials;
        }
    }
}

async function logoutUser(showNotification = true) {
    if (authToken) {
        try {
            await fetch("/api/auth/logout", {
                method: "POST",
                headers: { "Authorization": `Bearer ${authToken}` }
            });
        } catch (e) {
            console.warn("Logout endpoint error:", e);
        }
    }
    authToken = null;
    currentUser = null;
    localStorage.removeItem("aero_auth_token");
    conversationHistory = [];

    showAuthGate();
    if (showNotification) {
        showToast("Signed out successfully", "🔒");
    }
}

// Expose logoutUser globally to window
window.logoutUser = logoutUser;

function setupAuthListeners() {
    // 1. Gate Screen Tabs (Sign In vs Register)
    const gateTabLogin = document.getElementById("gateTabLogin");
    const gateTabReg = document.getElementById("gateTabRegister");
    const gateFormLogin = document.getElementById("gateLoginForm");
    const gateFormReg = document.getElementById("gateRegisterForm");

    if (gateTabLogin && gateTabReg) {
        gateTabLogin.addEventListener("click", (e) => {
            e.preventDefault();
            gateTabLogin.classList.add("active");
            gateTabReg.classList.remove("active");
            gateFormLogin.style.display = "flex";
            gateFormReg.style.display = "none";
        });

        gateTabReg.addEventListener("click", (e) => {
            e.preventDefault();
            gateTabReg.classList.add("active");
            gateTabLogin.classList.remove("active");
            gateFormReg.style.display = "flex";
            gateFormLogin.style.display = "none";
            populateGateTenantSelect();
        });
    }

    // 2. Gate Screen Login Submit
    if (gateFormLogin) {
        gateFormLogin.addEventListener("submit", async (e) => {
            e.preventDefault();
            const email = document.getElementById("gateLoginEmail").value.trim();
            const password = document.getElementById("gateLoginPassword").value;
            const btn = document.getElementById("btnGateLoginSubmit");
            
            btn.disabled = true;
            btn.innerHTML = `<span>Authenticating...</span> ⏳`;

            try {
                const res = await fetch("/api/auth/login", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ email, password })
                });
                const data = await res.json();
                if (res.ok) {
                    authToken = data.token;
                    currentUser = data.user;
                    localStorage.setItem("aero_auth_token", authToken);
                    showToast(`Welcome back, ${currentUser.full_name}!`, "👋");
                    showDashboard(currentUser);
                } else {
                    alert(data.detail || "Invalid credentials.");
                }
            } catch (err) {
                alert("Server connection failed. Ensure server is running.");
            } finally {
                btn.disabled = false;
                btn.innerHTML = `<span>Unlock Operations Dashboard</span> →`;
            }
        });
    }

    // 3. Gate Screen Register Submit
    if (gateFormReg) {
        gateFormReg.addEventListener("submit", async (e) => {
            e.preventDefault();
            const fullName = document.getElementById("gateRegFullName").value.trim();
            const email = document.getElementById("gateRegEmail").value.trim();
            const password = document.getElementById("gateRegPassword").value;
            const tenantId = document.getElementById("gateRegTenantSelect").value;
            const btn = document.getElementById("btnGateRegisterSubmit");

            btn.disabled = true;
            btn.innerHTML = `<span>Creating account...</span> ⏳`;

            try {
                const res = await fetch("/api/auth/register", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        full_name: fullName,
                        email,
                        password,
                        tenant_id: tenantId,
                        role: "OWNER"
                    })
                });
                const data = await res.json();
                if (res.ok) {
                    authToken = data.token;
                    currentUser = data.user;
                    localStorage.setItem("aero_auth_token", authToken);
                    showToast(`Account created for ${currentUser.full_name}!`, "🎉");
                    showDashboard(currentUser);
                } else {
                    alert(data.detail || "Registration failed.");
                }
            } catch (err) {
                alert("Server connection failed. Ensure server is running.");
            } finally {
                btn.disabled = false;
                btn.innerHTML = `<span>Create Account & Enter Dashboard</span> →`;
            }
        });
    }
}

// ----------------- Multi-Tenant Management ----------------- //

async function fetchTenants() {
    const select = document.getElementById("tenantSelect");
    try {
        const res = await fetch("/api/tenants");
        const tenants = await res.json();
        allTenantsCache = tenants;
        if (select) {
            select.innerHTML = tenants.map(t => `
                <option value="${t.tenant_id}" ${t.tenant_id === currentTenantId ? 'selected' : ''}>
                    ${t.name} (${t.tenant_id})
                </option>
            `).join("");
        }
        populateGateTenantSelect();
    } catch (e) {
        console.error("Failed to load tenants", e);
    }
}

function switchTenant(tenantId) {
    currentTenantId = tenantId;
    localStorage.setItem("aero_active_tenant", tenantId);
    
    // Update select dropdown
    const select = document.getElementById("tenantSelect");
    if (select) select.value = tenantId;

    // Update CSV export link
    const exportBtn = document.getElementById("btnExportCsv");
    if (exportBtn) {
        exportBtn.href = `/api/export/csv?tenant_id=${tenantId}`;
    }

    // Reset Chat for new tenant
    conversationHistory = [];
    const container = document.getElementById("chatMessages");
    if (container) {
        container.innerHTML = `
            <div class="message system-msg">
                <div class="msg-avatar">⚡</div>
                <div class="msg-content">
                    <p>Switched to business tenant: <strong>[${tenantId}]</strong>. How can I assist with your operations?</p>
                </div>
            </div>
        `;
    }

    // Update Floating Agent widget tenant badge & messages
    const floatBadge = document.getElementById("floatTenantBadge");
    if (floatBadge) floatBadge.textContent = tenantId;

    const floatContainer = document.getElementById("floatChatMessages");
    if (floatContainer) {
        floatContainer.innerHTML = `
            <div class="message system-msg">
                <div class="msg-avatar">⚡</div>
                <div class="msg-content">
                    <p>Switched to tenant <strong>[${tenantId}]</strong>. How can I assist with your operations?</p>
                </div>
            </div>
        `;
    }

    showToast(`Switched active tenant to ${tenantId}`, "🏢");
    refreshAllTenantData();
}

function refreshAllTenantData() {
    fetchDashboardMetrics();
    fetchInventory();
    fetchForecast();
    fetchSales();
    fetchTasks();
}

// Helper for tenant-aware & authenticated fetch
function tenantFetch(url, options = {}) {
    options.headers = options.headers || {};
    if (options.headers instanceof Headers) {
        options.headers.set("X-Tenant-ID", currentTenantId);
        if (authToken) {
            options.headers.set("Authorization", `Bearer ${authToken}`);
        }
    } else {
        options.headers["X-Tenant-ID"] = currentTenantId;
        if (authToken) {
            options.headers["Authorization"] = `Bearer ${authToken}`;
        }
    }
    return fetch(url, options);
}

// ----------------- SaaS Sidebar Navigation & Drawer ----------------- //

function setupSidebarListeners() {
    const sidebar = document.getElementById("saasSidebar");
    const btnCollapse = document.getElementById("btnSidebarCollapse");
    const btnMobileMenu = document.getElementById("btnMobileMenuToggle");
    const btnCloseMobile = document.getElementById("btnSidebarCloseMobile");
    const backdrop = document.getElementById("sidebarBackdrop");
    const btnSideLogout = document.getElementById("btnSideLogout");

    // 1. Desktop Sidebar Collapse Toggle
    if (btnCollapse && sidebar) {
        btnCollapse.addEventListener("click", () => {
            sidebar.classList.toggle("collapsed");
            const isCollapsed = sidebar.classList.contains("collapsed");
            localStorage.setItem("aero_sidebar_collapsed", isCollapsed);
            showToast(isCollapsed ? "Sidebar collapsed" : "Sidebar expanded", "📐");
        });
    }

    // 2. Mobile Off-Canvas Drawer Open/Close
    const closeMobileSidebar = () => {
        if (sidebar) sidebar.classList.remove("mobile-open");
        if (backdrop) backdrop.classList.remove("active");
    };

    if (btnMobileMenu && sidebar && backdrop) {
        btnMobileMenu.addEventListener("click", () => {
            sidebar.classList.add("mobile-open");
            backdrop.classList.add("active");
        });
    }

    if (btnCloseMobile) {
        btnCloseMobile.addEventListener("click", closeMobileSidebar);
    }
    if (backdrop) {
        backdrop.addEventListener("click", closeMobileSidebar);
    }

    // 3. Sidebar Navigation Item Clicks
    document.querySelectorAll(".sidebar-nav-item").forEach(item => {
        item.addEventListener("click", (e) => {
            e.preventDefault();
            const tabTarget = item.getAttribute("data-tab-target");
            const navTarget = item.getAttribute("data-nav-target");
            const itemId = item.id;

            if (tabTarget) {
                // Switch active tab on right dashboard panel
                const tabBtn = document.querySelector(`.tabs-nav .tab-btn[data-tab="${tabTarget}"]`);
                const tabContent = document.getElementById(tabTarget);
                if (tabBtn && tabContent) {
                    document.querySelectorAll(".tabs-nav .tab-btn").forEach(b => b.classList.remove("active"));
                    document.querySelectorAll(".tab-content").forEach(c => c.classList.remove("active"));
                    tabBtn.classList.add("active");
                    tabContent.classList.add("active");
                }

                document.querySelectorAll(".sidebar-nav-item").forEach(i => i.classList.remove("active"));
                item.classList.add("active");

                const breadcrumb = document.getElementById("breadcrumbActiveSection");
                const textEl = item.querySelector(".nav-item-text");
                if (breadcrumb && textEl) {
                    breadcrumb.textContent = textEl.textContent;
                }

                closeMobileSidebar();
            } else if (navTarget === "copilot") {
                document.querySelectorAll(".sidebar-nav-item").forEach(i => i.classList.remove("active"));
                item.classList.add("active");
                const breadcrumb = document.getElementById("breadcrumbActiveSection");
                if (breadcrumb) breadcrumb.textContent = "AI Copilot";
                focusChatInput();
                closeMobileSidebar();
            } else if (itemId === "sideNavExpenses") {
                sendChatMessage("What are our recent business expenses, run rate, and vendor breakdown?");
                closeMobileSidebar();
            } else if (itemId === "sideNavShifts") {
                sendChatMessage("Show me the current employee shifts, assigned roles, and total hours scheduled.");
                closeMobileSidebar();
            } else if (itemId === "sideNavReviews") {
                sendChatMessage("Analyze our latest customer feedback, ratings, and sentiment highlights.");
                closeMobileSidebar();
            } else if (itemId === "sideNavMorningBrief") {
                sendChatMessage("Generate my daily executive morning briefing and dispatch report to webhook channels.");
                closeMobileSidebar();
            }
        });
    });

    // 4. Sidebar Sign Out Button
    if (btnSideLogout) {
        btnSideLogout.addEventListener("click", () => {
            logoutUser(true);
        });
    }
}

// ----------------- Event Listeners ----------------- //

function setupEventListeners() {
    // Tenant selector change
    const tenantSelect = document.getElementById("tenantSelect");
    if (tenantSelect) {
        tenantSelect.addEventListener("change", (e) => {
            switchTenant(e.target.value);
        });
    }

    // New Tenant Modal
    const btnNewTenantOpen = document.getElementById("btnNewTenantModalOpen");
    const modalNewTenant = document.getElementById("newTenantModal");
    const btnCancelTenant = document.getElementById("btnCancelTenantModal");
    const btnConfirmTenant = document.getElementById("btnConfirmCreateTenant");

    if (btnNewTenantOpen && modalNewTenant) {
        btnNewTenantOpen.addEventListener("click", () => {
            modalNewTenant.style.display = "flex";
        });
    }
    if (btnCancelTenant && modalNewTenant) {
        btnCancelTenant.addEventListener("click", () => {
            modalNewTenant.style.display = "none";
        });
    }
    if (btnConfirmTenant && modalNewTenant) {
        btnConfirmTenant.addEventListener("click", async () => {
            const nameInput = document.getElementById("tenantNameInput");
            const tidInput = document.getElementById("tenantIdInput");
            const indInput = document.getElementById("tenantIndustryInput");

            const name = nameInput ? nameInput.value.trim() : "";
            const tid = tidInput ? tidInput.value.trim().toLowerCase().replace(/\s+/g, '-') : "";
            const industry = indInput ? indInput.value.trim() || "Retail" : "Retail";

            if (!name || !tid) {
                alert("Please provide both Business Name and Tenant ID slug.");
                return;
            }

            try {
                const res = await fetch("/api/tenants", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ tenant_id: tid, name: name, industry: industry })
                });
                const data = await res.json();
                if (res.ok) {
                    showToast(`Tenant '${name}' created!`, "🏢");
                    modalNewTenant.style.display = "none";
                    await fetchTenants();
                    switchTenant(tid);
                } else {
                    alert(`Error: ${data.detail || 'Could not create tenant'}`);
                }
            } catch (e) {
                alert("Failed to connect to server.");
            }
        });
    }

    // Theme Toggle
    const btnTheme = document.getElementById("btnThemeToggle");
    if (btnTheme) {
        btnTheme.addEventListener("click", () => {
            document.body.classList.toggle("light-theme");
            const isLight = document.body.classList.contains("light-theme");
            localStorage.setItem("aero_theme", isLight ? "light" : "dark");
            showToast(isLight ? "Switched to Light Theme" : "Switched to Dark Theme", "🌓");
            if (salesChartInstance) {
                fetchSales();
            }
        });
    }

    // Sidebar Listeners & Drawer Handling
    setupSidebarListeners();

    // Tab Switching inside Right Dashboard Hub (Synced with Sidebar)
    document.querySelectorAll(".tabs-nav .tab-btn").forEach(btn => {
        btn.addEventListener("click", () => {
            const targetId = btn.getAttribute("data-tab");
            if (!targetId) return;
            const targetEl = document.getElementById(targetId);
            if (!targetEl) return;

            document.querySelectorAll(".tabs-nav .tab-btn").forEach(b => b.classList.remove("active"));
            document.querySelectorAll(".tab-content").forEach(c => c.classList.remove("active"));
            btn.classList.add("active");
            targetEl.classList.add("active");

            // Sync with sidebar navigation items
            document.querySelectorAll(".sidebar-nav-item").forEach(item => {
                if (item.getAttribute("data-tab-target") === targetId) {
                    item.classList.add("active");
                    const textEl = item.querySelector(".nav-item-text");
                    const breadcrumb = document.getElementById("breadcrumbActiveSection");
                    if (breadcrumb && textEl) breadcrumb.textContent = textEl.textContent;
                } else {
                    item.classList.remove("active");
                }
            });
        });
    });

    // Chat Form
    const chatForm = document.getElementById("chatForm");
    if (chatForm) {
        chatForm.addEventListener("submit", async (e) => {
            e.preventDefault();
            const input = document.getElementById("userInput");
            if (!input) return;
            const msg = input.value.trim();
            if (!msg) return;
            input.value = "";
            await sendChatMessage(msg);
        });
    }

    // Quick Prompt Chips
    document.querySelectorAll(".chip-btn").forEach(chip => {
        chip.addEventListener("click", () => {
            const prompt = chip.getAttribute("data-prompt");
            if (prompt) sendChatMessage(prompt);
        });
    });

    // Reset Chat
    const btnClearChat = document.getElementById("btnClearChat");
    if (btnClearChat) {
        btnClearChat.addEventListener("click", () => {
            conversationHistory = [];
            const container = document.getElementById("chatMessages");
            if (container) {
                container.innerHTML = `
                    <div class="message system-msg">
                        <div class="msg-avatar">⚡</div>
                        <div class="msg-content">
                            <p><strong>Chat reset.</strong> How can I assist with your operations in [${currentTenantId}]?</p>
                        </div>
                    </div>
                `;
            }
            showToast("Conversation cleared", "↺");
        });
    }

    // Refresh Inventory Button
    const btnRefInv = document.getElementById("btnRefreshInventory");
    if (btnRefInv) {
        btnRefInv.addEventListener("click", () => {
            fetchInventory();
            fetchDashboardMetrics();
            showToast("Inventory refreshed", "📦");
        });
    }

    // Refresh Forecast Button
    const btnForecast = document.getElementById("btnRefreshForecast");
    if (btnForecast) {
        btnForecast.addEventListener("click", () => {
            fetchForecast();
            showToast("Demand forecast refreshed", "📈");
        });
    }

    // Refresh Chart Button
    const btnRefChart = document.getElementById("btnRefreshChart");
    if (btnRefChart) {
        btnRefChart.addEventListener("click", () => {
            fetchSales();
            showToast("Chart telemetry refreshed", "📊");
        });
    }

    // Inventory Search & Category Filter Listeners
    const invSearchInput = document.getElementById("inventorySearchInput");
    if (invSearchInput) {
        invSearchInput.addEventListener("input", () => {
            renderFilteredInventory();
        });
    }

    const invCatFilter = document.getElementById("inventoryCategoryFilter");
    if (invCatFilter) {
        invCatFilter.addEventListener("change", () => {
            renderFilteredInventory();
        });
    }

    // Forecast Search Listener
    const foreSearchInput = document.getElementById("forecastSearchInput");
    if (foreSearchInput) {
        foreSearchInput.addEventListener("input", () => {
            renderFilteredForecast();
        });
    }

    // Time Range Switcher
    document.querySelectorAll(".time-range-group .time-pill").forEach(pill => {
        pill.addEventListener("click", () => {
            document.querySelectorAll(".time-range-group .time-pill").forEach(p => p.classList.remove("active"));
            pill.classList.add("active");
            const range = pill.getAttribute("data-range");
            showToast(`Telemetry range: ${range.toUpperCase()}`, "⏱️");
            refreshAllTenantData();
        });
    });

    // Add Product Modal
    const btnAddProdOpen = document.getElementById("btnAddProductModalOpen");
    const modalAddProd = document.getElementById("addProductModal");
    const btnCancelAddProd = document.getElementById("btnCancelAddProd");
    const btnConfirmAddProd = document.getElementById("btnConfirmAddProd");

    if (btnAddProdOpen && modalAddProd) {
        btnAddProdOpen.addEventListener("click", () => {
            modalAddProd.style.display = "flex";
        });
    }
    if (btnCancelAddProd && modalAddProd) {
        btnCancelAddProd.addEventListener("click", () => {
            modalAddProd.style.display = "none";
        });
    }
    if (btnConfirmAddProd && modalAddProd) {
        btnConfirmAddProd.addEventListener("click", async () => {
            const nameEl = document.getElementById("addProdName");
            const skuEl = document.getElementById("addProdSku");
            const catEl = document.getElementById("addProdCategory");
            const stockEl = document.getElementById("addProdStock");
            const threshEl = document.getElementById("addProdThreshold");
            const priceEl = document.getElementById("addProdPrice");
            const costEl = document.getElementById("addProdCost");

            const name = nameEl ? nameEl.value.trim() : "";
            const sku = skuEl ? skuEl.value.trim() : "";
            const category = catEl ? catEl.value.trim() : "General";
            const stock = stockEl ? parseInt(stockEl.value, 10) || 20 : 20;
            const threshold = threshEl ? parseInt(threshEl.value, 10) || 10 : 10;
            const price = priceEl ? parseFloat(priceEl.value) || 49.99 : 49.99;
            const cost = costEl ? parseFloat(costEl.value) || 20.00 : 20.00;

            if (!name || !sku) {
                alert("Please enter both Product Name and SKU.");
                return;
            }

            try {
                const res = await tenantFetch("/api/products/add", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        sku, name, category,
                        stock_quantity: stock,
                        low_stock_threshold: threshold,
                        unit_price: price,
                        cost_price: cost
                    })
                });
                const data = await res.json();
                if (res.ok) {
                    showToast(`Product ${name} added to ${currentTenantId}!`, "📦");
                    modalAddProd.style.display = "none";
                    fetchInventory();
                    fetchForecast();
                    fetchDashboardMetrics();
                } else {
                    alert(`Error: ${data.detail || 'Could not add product'}`);
                }
            } catch (err) {
                alert("Failed to connect to server.");
            }
        });
    }

    // New Order Modal
    const modalNewOrder = document.getElementById("newOrderModal");
    const btnCancelOrder = document.getElementById("btnCancelOrder");
    const btnConfirmOrder = document.getElementById("btnConfirmOrder");

    async function openNewOrderModal() {
        if (!modalNewOrder) return;
        const select = document.getElementById("orderProductSelect");
        if (select) {
            select.innerHTML = '<option value="">Loading products...</option>';
            try {
                const res = await tenantFetch("/api/products");
                const data = await res.json();
                if (data.products && data.products.length > 0) {
                    select.innerHTML = "";
                    data.products.forEach(p => {
                        const opt = document.createElement("option");
                        opt.value = p.sku;
                        opt.textContent = `${p.name} (${p.sku}) — Stock: ${p.stock_quantity} ($${p.unit_price})`;
                        select.appendChild(opt);
                    });
                } else {
                    const resForecast = await tenantFetch("/api/forecast");
                    const dataForecast = await resForecast.json();
                    if (dataForecast.forecasts && dataForecast.forecasts.length > 0) {
                        select.innerHTML = "";
                        dataForecast.forecasts.forEach(p => {
                            const opt = document.createElement("option");
                            opt.value = p.sku;
                            opt.textContent = `${p.name} (${p.sku}) — Stock: ${p.current_stock}`;
                            select.appendChild(opt);
                        });
                    }
                }
            } catch (e) {
                console.error("Failed to load products for new order modal:", e);
                select.innerHTML = '<option value="SKU-101">Standard Product (SKU-101)</option>';
            }
        }
        modalNewOrder.style.display = "flex";
        const custEl = document.getElementById("orderCustName");
        if (custEl) custEl.focus();
    }

    // Attach open handler to all New Order buttons
    document.querySelectorAll(".btn-open-new-order, #btnNewOrderModalOpen, #btnTopNewOrder, #btnSalesNewOrder").forEach(btn => {
        btn.addEventListener("click", (e) => {
            e.preventDefault();
            openNewOrderModal();
        });
    });

    if (btnCancelOrder && modalNewOrder) {
        btnCancelOrder.addEventListener("click", () => {
            modalNewOrder.style.display = "none";
        });
    }

    if (modalNewOrder) {
        modalNewOrder.addEventListener("click", (e) => {
            if (e.target === modalNewOrder) {
                modalNewOrder.style.display = "none";
            }
        });
    }

    if (btnConfirmOrder && modalNewOrder) {
        btnConfirmOrder.addEventListener("click", async () => {
            const custEl = document.getElementById("orderCustName");
            const prodEl = document.getElementById("orderProductSelect");
            const qtyEl = document.getElementById("orderQty");

            const customer = custEl ? custEl.value.trim() || "Retail Customer" : "Retail Customer";
            const sku = prodEl ? prodEl.value : "";
            const qty = qtyEl ? parseInt(qtyEl.value, 10) || 1 : 1;

            if (!sku) {
                alert("Please select a product SKU.");
                return;
            }

            btnConfirmOrder.disabled = true;
            btnConfirmOrder.textContent = "Processing...";

            try {
                const res = await tenantFetch("/api/orders/create", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ customer_name: customer, sku, quantity: qty })
                });
                const data = await res.json();
                if (res.ok) {
                    showToast(`Order ${data.order_id} created ($${data.total_amount})!`, "🎉");
                    modalNewOrder.style.display = "none";
                    if (custEl) custEl.value = "";
                    if (qtyEl) qtyEl.value = "1";
                    refreshAllTenantData();
                } else {
                    alert(`Order failed: ${data.detail || 'Insufficient stock'}`);
                }
            } catch (e) {
                alert("Failed to submit order.");
            } finally {
                btnConfirmOrder.disabled = false;
                btnConfirmOrder.textContent = "Submit Order";
            }
        });
    }

    // Add Task Modal
    const btnAddTaskOpen = document.getElementById("btnAddTaskModalOpen");
    const modalAddTask = document.getElementById("addTaskModal");
    const btnCancelTask = document.getElementById("btnCancelTaskModal");
    const btnConfirmTask = document.getElementById("btnConfirmAddTask");

    if (btnAddTaskOpen && modalAddTask) {
        btnAddTaskOpen.addEventListener("click", () => {
            modalAddTask.style.display = "flex";
        });
    }
    if (btnCancelTask && modalAddTask) {
        btnCancelTask.addEventListener("click", () => {
            modalAddTask.style.display = "none";
        });
    }
    if (btnConfirmTask && modalAddTask) {
        btnConfirmTask.addEventListener("click", async () => {
            const titleEl = document.getElementById("taskTitleInput");
            const prioEl = document.getElementById("taskPrioritySelect");
            const assignEl = document.getElementById("taskAssigneeInput");

            const title = titleEl ? titleEl.value.trim() : "";
            const priority = prioEl ? prioEl.value : "MEDIUM";
            const assignedTo = assignEl ? assignEl.value.trim() || "Business Owner" : "Business Owner";

            if (!title) {
                alert("Please enter a task title.");
                return;
            }

            try {
                const res = await tenantFetch("/api/tasks", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        title,
                        priority,
                        assigned_to: assignedTo,
                        due_date: new Date().toISOString().split("T")[0]
                    })
                });
                const data = await res.json();
                if (res.ok) {
                    showToast(`Task created: "${title}"`, "📋");
                    modalAddTask.style.display = "none";
                    if (titleEl) titleEl.value = "";
                    fetchTasks();
                    fetchDashboardMetrics();
                } else {
                    alert(`Task creation failed: ${data.detail || 'Error'}`);
                }
            } catch (err) {
                alert("Failed to create task.");
            }
        });
    }
}

// ----------------- Speech Recognition (Voice) ----------------- //

function setupSpeechRecognition() {
    const btnMic = document.getElementById("btnMic");
    const input = document.getElementById("userInput");
    if (!btnMic) return;

    if (!('webkitSpeechRecognition' in window) && !('SpeechRecognition' in window)) {
        btnMic.style.display = "none";
        return;
    }

    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    const recognition = new SpeechRecognition();
    recognition.continuous = false;
    recognition.interimResults = false;
    recognition.lang = 'en-US';

    btnMic.addEventListener("click", () => {
        if (btnMic.classList.contains("listening")) {
            recognition.stop();
        } else {
            recognition.start();
            btnMic.classList.add("listening");
            showToast("Listening... speak your operational request", "🎤");
        }
    });

    recognition.onresult = (event) => {
        const transcript = event.results[0][0].transcript;
        if (input) input.value = transcript;
        btnMic.classList.remove("listening");
        sendChatMessage(transcript);
    };

    recognition.onerror = () => btnMic.classList.remove("listening");
    recognition.onend = () => btnMic.classList.remove("listening");
}

// ----------------- Dashboard Data Fetching (Tenant Scoped) ----------------- //

async function fetchDashboardMetrics() {
    try {
        const [salesRes, invRes, tasksRes] = await Promise.all([
            tenantFetch("/api/sales/summary"),
            tenantFetch("/api/inventory/status"),
            tenantFetch("/api/tasks?status=PENDING")
        ]);

        const sales = await salesRes.json();
        const inv = await invRes.json();
        const tasks = await tasksRes.json();

        const lowStockCount = inv.low_stock_count || 0;
        const taskCount = tasks.total_tasks || 0;

        document.getElementById("metricRevenue").textContent = `$${(sales.total_revenue || 0).toFixed(2)}`;
        document.getElementById("metricAov").textContent = `AOV: $${(sales.average_order_value || 0).toFixed(2)}`;
        document.getElementById("metricOrders").textContent = sales.total_orders || 0;
        document.getElementById("metricLowStock").textContent = lowStockCount;
        document.getElementById("metricTasks").textContent = taskCount;

        // Update Sidebar Badges
        const sideBadgeLowStock = document.getElementById("sideBadgeLowStock");
        if (sideBadgeLowStock) {
            if (lowStockCount > 0) {
                sideBadgeLowStock.textContent = lowStockCount;
                sideBadgeLowStock.style.display = "inline-block";
            } else {
                sideBadgeLowStock.style.display = "none";
            }
        }

        const sideBadgeTasks = document.getElementById("sideBadgeTasks");
        if (sideBadgeTasks) {
            if (taskCount > 0) {
                sideBadgeTasks.textContent = taskCount;
                sideBadgeTasks.style.display = "inline-block";
            } else {
                sideBadgeTasks.style.display = "none";
            }
        }
    } catch (err) {
        console.error("Error fetching metrics:", err);
    }
}

let cachedInventoryAlerts = [];
let cachedForecastList = [];

async function fetchInventory() {
    const tbody = document.getElementById("inventoryTableBody");
    const countLabel = document.getElementById("inventoryCountLabel");
    try {
        const res = await tenantFetch("/api/inventory/status");
        const data = await res.json();
        cachedInventoryAlerts = data.critical_alerts || [];

        // Populate Category Filter dropdown
        populateCategoryFilter(cachedInventoryAlerts);
        renderFilteredInventory();
    } catch (err) {
        tbody.innerHTML = `<tr><td colspan="6" class="text-center" style="color:var(--danger); padding: 1.5rem;">Error loading inventory telemetry.</td></tr>`;
        if (countLabel) countLabel.textContent = "Sync error";
    }
}

function populateCategoryFilter(items) {
    const catSelect = document.getElementById("inventoryCategoryFilter");
    if (!catSelect) return;
    const currentVal = catSelect.value || "ALL";
    const categories = Array.from(new Set(items.map(i => i.category || 'General'))).sort();
    catSelect.innerHTML = `<option value="ALL">All Categories (${items.length})</option>` + 
        categories.map(c => `<option value="${c}">${c}</option>`).join("");
    catSelect.value = currentVal;
}

function renderFilteredInventory() {
    const tbody = document.getElementById("inventoryTableBody");
    const countLabel = document.getElementById("inventoryCountLabel");
    const searchInput = document.getElementById("inventorySearchInput");
    const catSelect = document.getElementById("inventoryCategoryFilter");

    const query = searchInput ? searchInput.value.trim().toLowerCase() : "";
    const category = catSelect ? catSelect.value : "ALL";

    let filtered = cachedInventoryAlerts.filter(item => {
        const matchesQuery = !query || 
            (item.sku && item.sku.toLowerCase().includes(query)) ||
            (item.name && item.name.toLowerCase().includes(query)) ||
            (item.category && item.category.toLowerCase().includes(query));
        const matchesCat = category === "ALL" || (item.category || 'General') === category;
        return matchesQuery && matchesCat;
    });

    if (countLabel) {
        countLabel.textContent = `Showing ${filtered.length} of ${cachedInventoryAlerts.length} watchlist items [${currentTenantId}]`;
    }

    if (!filtered || filtered.length === 0) {
        if (cachedInventoryAlerts.length === 0) {
            tbody.innerHTML = `<tr><td colspan="6" class="text-center" style="color: var(--success); padding: 2rem;"><span class="status-badge status-healthy" style="font-size: 0.85rem; padding: 0.4rem 1rem;"><span class="status-indicator-dot"></span> All inventory items for [${currentTenantId}] are healthy & well-stocked</span></td></tr>`;
        } else {
            tbody.innerHTML = `<tr><td colspan="6" class="text-center" style="color: var(--text-dim); padding: 2rem;">No items match the current search or category filter.</td></tr>`;
        }
        return;
    }

    tbody.innerHTML = filtered.map(item => {
        const isCritical = item.severity === 'CRITICAL';
        const statusClass = isCritical ? 'status-critical' : 'status-warning';
        const cleanName = (item.name || '').replace(/'/g, "\\'");
        return `
            <tr>
                <td><span class="sku-pill">${item.sku}</span></td>
                <td>
                    <div class="table-prod-name">${item.name}</div>
                    <div class="table-prod-category">${item.category || 'General'}</div>
                </td>
                <td><span class="stock-qty ${isCritical ? 'stock-critical' : 'stock-warning'}">${item.current_stock}</span> <span class="stock-unit">units</span></td>
                <td><span class="threshold-val">${item.threshold}</span> <span class="stock-unit">min</span></td>
                <td>
                    <span class="status-badge ${statusClass}">
                        <span class="status-indicator-dot"></span>
                        ${item.severity}
                    </span>
                </td>
                <td>
                    <button class="btn-table-reorder" onclick="openReorderModal('${item.sku}', '${cleanName}', ${item.recommended_reorder})">
                        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"/></svg>
                        <span>Reorder (+${item.recommended_reorder})</span>
                    </button>
                </td>
            </tr>
        `;
    }).join("");
}

async function fetchForecast() {
    const tbody = document.getElementById("forecastTableBody");
    const countLabel = document.getElementById("forecastCountLabel");
    if (!tbody) return;
    try {
        const res = await tenantFetch("/api/forecast");
        const data = await res.json();
        cachedForecastList = data.forecasts || [];
        renderFilteredForecast();
    } catch (err) {
        tbody.innerHTML = `<tr><td colspan="6" class="text-center" style="color:var(--danger); padding: 1.5rem;">Error loading demand forecast.</td></tr>`;
        if (countLabel) countLabel.textContent = "Sync error";
    }
}

function renderFilteredForecast() {
    const tbody = document.getElementById("forecastTableBody");
    const countLabel = document.getElementById("forecastCountLabel");
    const searchInput = document.getElementById("forecastSearchInput");

    const query = searchInput ? searchInput.value.trim().toLowerCase() : "";

    let filtered = cachedForecastList.filter(item => {
        return !query || 
            (item.sku && item.sku.toLowerCase().includes(query)) ||
            (item.name && item.name.toLowerCase().includes(query));
    });

    if (countLabel) {
        countLabel.textContent = `Projecting ${filtered.length} product run rates [${currentTenantId}]`;
    }

    if (!filtered || filtered.length === 0) {
        tbody.innerHTML = `<tr><td colspan="6" class="text-center" style="padding: 2rem; color: var(--text-dim);">No forecast records match the search filter.</td></tr>`;
        return;
    }

    tbody.innerHTML = filtered.map(item => {
        const riskClass = item.stockout_risk === 'HIGH' ? 'status-critical' : (item.stockout_risk === 'MEDIUM' ? 'status-warning' : 'status-healthy');
        const etaClass = item.days_until_stockout <= 3 ? 'eta-danger' : (item.days_until_stockout <= 7 ? 'eta-warning' : 'eta-healthy');
        return `
            <tr>
                <td>
                    <div class="table-prod-name">${item.name}</div>
                    <span class="sku-pill-sub">${item.sku}</span>
                </td>
                <td><span class="stock-qty">${item.current_stock}</span> <span class="stock-unit">units</span></td>
                <td><span class="velocity-pill">~${item.daily_velocity} / day</span></td>
                <td><span class="eta-pill ${etaClass}">${item.days_until_stockout} days</span></td>
                <td><strong>${item.forecast_7_days}</strong> <span class="stock-unit">units</span></td>
                <td>
                    <span class="status-badge ${riskClass}">
                        <span class="status-indicator-dot"></span>
                        ${item.stockout_risk} RISK
                    </span>
                </td>
            </tr>
        `;
    }).join("");
}

async function fetchSales() {
    try {
        const res = await tenantFetch("/api/sales/summary");
        const data = await res.json();

        const topContainer = document.getElementById("topProductsContainer");
        if (data.top_selling_products && data.top_selling_products.length > 0) {
            topContainer.innerHTML = data.top_selling_products.map(p => `
                <div class="top-prod-card">
                    <div class="top-prod-title">${p.name}</div>
                    <div class="top-prod-stat">
                        <span class="top-prod-units">${p.units_sold} units sold</span>
                        <span class="top-prod-rev">$${p.total_revenue.toFixed(2)}</span>
                    </div>
                </div>
            `).join("");

            renderAnalyticsChart(data.top_selling_products);
        } else {
            topContainer.innerHTML = `<div style="font-size:0.8rem; color:var(--text-muted); padding: 0.5rem;">No sales recorded today for ${currentTenantId}.</div>`;
        }

        const tbody = document.getElementById("salesTableBody");
        if (data.recent_orders && data.recent_orders.length > 0) {
            tbody.innerHTML = data.recent_orders.map(o => `
                <tr>
                    <td><span class="sku-pill">${o.order_id}</span></td>
                    <td><strong>${o.customer_name}</strong></td>
                    <td><span class="amount-val">$${o.total_amount.toFixed(2)}</span></td>
                    <td>
                        <span class="status-badge status-healthy">
                            <span class="status-indicator-dot"></span>
                            ${o.payment_status}
                        </span>
                    </td>
                    <td>
                        <span class="status-badge status-warning">
                            <span class="status-indicator-dot"></span>
                            ${o.fulfillment_status}
                        </span>
                    </td>
                </tr>
            `).join("");
        } else {
            tbody.innerHTML = `<tr><td colspan="5" class="text-center" style="color:var(--text-muted); padding: 1.5rem;">No recent orders recorded.</td></tr>`;
        }
    } catch (err) {
        console.error("Error fetching sales:", err);
    }
}

function renderAnalyticsChart(topProducts) {
    const canvas = document.getElementById("salesChart");
    if (!canvas || typeof Chart === "undefined") return;

    const labels = topProducts.map(p => p.name.length > 18 ? p.name.substring(0, 16) + '..' : p.name);
    const revenues = topProducts.map(p => p.total_revenue);
    const units = topProducts.map(p => p.units_sold);

    if (salesChartInstance) {
        salesChartInstance.destroy();
    }

    const ctx = canvas.getContext("2d");
    
    // Create modern gradients for bars
    const revGradient = ctx.createLinearGradient(0, 0, 0, 240);
    revGradient.addColorStop(0, 'rgba(56, 189, 248, 0.9)');
    revGradient.addColorStop(1, 'rgba(14, 165, 233, 0.25)');

    const unitGradient = ctx.createLinearGradient(0, 0, 0, 240);
    unitGradient.addColorStop(0, 'rgba(52, 211, 153, 0.9)');
    unitGradient.addColorStop(1, 'rgba(16, 185, 129, 0.25)');

    salesChartInstance = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: labels,
            datasets: [
                {
                    label: 'Gross Revenue ($)',
                    data: revenues,
                    backgroundColor: revGradient,
                    borderColor: '#38bdf8',
                    borderWidth: 1.5,
                    borderRadius: 8,
                    yAxisID: 'y'
                },
                {
                    label: 'Units Sold',
                    data: units,
                    backgroundColor: unitGradient,
                    borderColor: '#34d399',
                    borderWidth: 1.5,
                    borderRadius: 8,
                    yAxisID: 'y1'
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                y: {
                    type: 'linear',
                    display: true,
                    position: 'left',
                    grid: { color: 'rgba(255, 255, 255, 0.05)' },
                    ticks: {
                        color: '#94a3b8',
                        callback: function(value) { return '$' + value; }
                    }
                },
                y1: {
                    type: 'linear',
                    display: true,
                    position: 'right',
                    grid: { drawOnChartArea: false },
                    ticks: { color: '#64748b' }
                },
                x: {
                    grid: { display: false },
                    ticks: { color: '#94a3b8' }
                }
            },
            plugins: {
                legend: {
                    labels: {
                        color: '#f8fafc',
                        font: { family: 'Plus Jakarta Sans', weight: '600' }
                    }
                },
                tooltip: {
                    backgroundColor: 'rgba(15, 23, 42, 0.95)',
                    titleColor: '#f8fafc',
                    bodyColor: '#94a3b8',
                    borderColor: 'rgba(255, 255, 255, 0.1)',
                    borderWidth: 1,
                    padding: 12,
                    boxPadding: 6,
                    cornerRadius: 8
                }
            }
        }
    });
}

async function fetchTasks() {
    const container = document.getElementById("tasksListContainer") || document.getElementById("tasksContainer");
    if (!container) return;
    try {
        const res = await tenantFetch("/api/tasks");
        const data = await res.json();

        if (!data.tasks || data.tasks.length === 0) {
            container.innerHTML = `<div style="padding:2.5rem; text-align:center; color:var(--text-dim);"><p>No active tasks scheduled for [${currentTenantId}].</p></div>`;
            return;
        }

        container.innerHTML = data.tasks.map(t => {
            const isDone = t.status === "COMPLETED";
            let statusClass = t.priority === "CRITICAL" ? "status-critical" : (t.priority === "HIGH" ? "status-warning" : "status-healthy");
            return `
                <div class="task-item ${isDone ? 'completed' : ''}" id="task-${t.task_id}">
                    <div class="task-left">
                        <input type="checkbox" class="task-checkbox" ${isDone ? 'checked' : ''} onchange="toggleTaskStatus(${t.task_id}, this.checked)">
                        <div class="task-info">
                            <div class="task-title ${isDone ? 'completed' : ''}">${t.title}</div>
                            <div class="task-meta">Due: <strong>${t.due_date}</strong> • Assigned: <span>${t.assigned_to}</span> • Status: <strong style="color:var(--text-main)">${t.status}</strong></div>
                        </div>
                    </div>
                    <span class="status-badge ${statusClass}">
                        <span class="status-indicator-dot"></span>
                        ${t.priority}
                    </span>
                </div>
            `;
        }).join("");
    } catch (err) {
        console.error("Error fetching tasks:", err);
        container.innerHTML = `<div style="padding:1.5rem; text-align:center; color:var(--danger);"><p>Error loading tasks.</p></div>`;
    }
}

async function toggleTaskStatus(taskId, isChecked) {
    const newStatus = isChecked ? "COMPLETED" : "PENDING";
    try {
        const res = await tenantFetch(`/api/tasks/${taskId}/status`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ status: newStatus })
        });
        if (res.ok) {
            showToast(`Task #${taskId} marked as ${newStatus}`, isChecked ? "✅" : "📋");
            fetchTasks();
            fetchDashboardMetrics();
        }
    } catch (e) {
        alert("Failed to update task status.");
    }
}

// ----------------- Chat with Agent ----------------- //

async function sendChatMessage(userMsg) {
    appendMessage(userMsg, "user");
    const typingId = appendTypingIndicator();

    try {
        const res = await tenantFetch("/api/chat", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                message: userMsg,
                tenant_id: currentTenantId,
                history: conversationHistory
            })
        });

        removeTypingIndicator(typingId);

        if (!res.ok) {
            let errorMsg = "Error processing request with the agent.";
            try {
                const errData = await res.json();
                if (errData.detail) errorMsg = typeof errData.detail === "string" ? errData.detail : JSON.stringify(errData.detail);
                else if (errData.reply) errorMsg = errData.reply;
            } catch (e) {}
            appendMessage(`⚠️ ${errorMsg}`, "bot");
            return;
        }

        const data = await res.json();
        
        let toolPills = "";
        if (data.tool_calls && data.tool_calls.length > 0) {
            toolPills = data.tool_calls.map(tc => `<div class="tool-badge-pill">⚙️ Tool: ${tc.tool}()</div>`).join(" ");
        }

        appendMessage(data.reply, "bot", toolPills);
        
        conversationHistory.push({ role: "user", content: userMsg });
        conversationHistory.push({ role: "assistant", content: data.reply });

        refreshAllTenantData();

    } catch (err) {
        removeTypingIndicator(typingId);
        appendMessage("⚠️ Connection error reaching Productivity Agent server.", "bot");
    }
}

function appendMessage(text, sender, extraHtml = "") {
    const formatted = formatMarkdown(text);
    const avatar = sender === "user" ? "👤" : "⚡";
    const msgHtml = `
        <div class="msg-avatar">${avatar}</div>
        <div class="msg-content">
            ${extraHtml ? extraHtml : ''}
            <div>${formatted}</div>
        </div>
    `;

    // 1. In-page Main Chat Container
    const container = document.getElementById("chatMessages");
    if (container) {
        const div = document.createElement("div");
        div.className = `message ${sender}-msg`;
        div.innerHTML = msgHtml;
        container.appendChild(div);
        container.scrollTop = container.scrollHeight;
    }

    // 2. Floating Agent Widget Container
    const fContainer = document.getElementById("floatChatMessages");
    if (fContainer) {
        const fDiv = document.createElement("div");
        fDiv.className = `message ${sender}-msg`;
        fDiv.innerHTML = msgHtml;
        fContainer.appendChild(fDiv);
        fContainer.scrollTop = fContainer.scrollHeight;
    }

    // Show unread indicator on FAB if floating chat is minimized
    if (sender === "bot") {
        const floatCard = document.getElementById("aeroFloatCard");
        const unreadBadge = document.getElementById("floatUnreadBadge");
        if (floatCard && (floatCard.style.display === "none" || !floatCard.style.display)) {
            if (unreadBadge) unreadBadge.style.display = "flex";
        }
    }
}

function appendTypingIndicator() {
    const id = "typing-" + Date.now();
    const typingHtml = `
        <div class="msg-avatar">⚡</div>
        <div class="msg-content"><span class="pulse-dot"></span> Aero is analyzing [${currentTenantId}]...</div>
    `;

    const container = document.getElementById("chatMessages");
    if (container) {
        const div = document.createElement("div");
        div.className = "message bot-msg typing-indicator";
        div.id = id;
        div.innerHTML = typingHtml;
        container.appendChild(div);
        container.scrollTop = container.scrollHeight;
    }

    const fContainer = document.getElementById("floatChatMessages");
    if (fContainer) {
        const fDiv = document.createElement("div");
        fDiv.className = "message bot-msg typing-indicator";
        fDiv.id = id + "-float";
        fDiv.innerHTML = typingHtml;
        fContainer.appendChild(fDiv);
        fContainer.scrollTop = fContainer.scrollHeight;
    }

    return id;
}

function removeTypingIndicator(id) {
    const el1 = document.getElementById(id);
    if (el1) el1.remove();
    const el2 = document.getElementById(id + "-float");
    if (el2) el2.remove();
}

function formatMarkdown(text) {
    if (!text) return "";
    let html = text
        .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
        .replace(/\*(.*?)\*/g, '<em>$1</em>')
        .replace(/`(.*?)`/g, '<code>$1</code>')
        .replace(/\n\n/g, '<br><br>')
        .replace(/\n/g, '<br>');
    return html;
}

// ----------------- Floating Aero Operations Agent Widget ----------------- //

function setupFloatingAgentWidget() {
    const fab = document.getElementById("btnAeroFloatFab");
    const floatCard = document.getElementById("aeroFloatCard");
    const btnClose = document.getElementById("btnFloatClose");
    const btnDock = document.getElementById("btnFloatDock");
    const btnClear = document.getElementById("btnFloatClearChat");
    const floatForm = document.getElementById("floatChatForm");
    const floatInput = document.getElementById("floatUserInput");
    const floatMic = document.getElementById("btnFloatMic");
    const unreadBadge = document.getElementById("floatUnreadBadge");

    // 1. Toggle Open / Close Floating Widget
    if (fab && floatCard) {
        fab.addEventListener("click", () => {
            const isHidden = floatCard.style.display === "none" || !floatCard.style.display;
            if (isHidden) {
                floatCard.style.display = "flex";
                if (unreadBadge) unreadBadge.style.display = "none";
                const floatBadge = document.getElementById("floatTenantBadge");
                if (floatBadge) floatBadge.textContent = currentTenantId;
                setTimeout(() => {
                    if (floatInput) floatInput.focus();
                    const fContainer = document.getElementById("floatChatMessages");
                    if (fContainer) fContainer.scrollTop = fContainer.scrollHeight;
                }, 50);
            } else {
                floatCard.style.display = "none";
            }
        });
    }

    // 2. Close / Minimize Button
    if (btnClose && floatCard) {
        btnClose.addEventListener("click", () => {
            floatCard.style.display = "none";
        });
    }

    // 3. Expand / Restore Window Size Toggle Button
    if (btnDock && floatCard) {
        btnDock.addEventListener("click", () => {
            floatCard.classList.toggle("expanded");
            const isExp = floatCard.classList.contains("expanded");
            btnDock.textContent = isExp ? "⤡" : "⤢";
            btnDock.title = isExp ? "Restore compact size" : "Expand chat window";
            showToast(isExp ? "Expanded Copilot window" : "Restored compact size", "📐");
        });
    }

    // 4. Clear Floating Chat Button
    if (btnClear) {
        btnClear.addEventListener("click", () => {
            conversationHistory = [];
            const resetHtml = `
                <div class="message system-msg">
                    <div class="msg-avatar">⚡</div>
                    <div class="msg-content">
                        <p><strong>Chat reset.</strong> How can I assist with your operations in [${currentTenantId}]?</p>
                    </div>
                </div>
            `;
            const container = document.getElementById("chatMessages");
            if (container) container.innerHTML = resetHtml;
            const fContainer = document.getElementById("floatChatMessages");
            if (fContainer) fContainer.innerHTML = resetHtml;
            showToast("Conversation cleared", "↺");
        });
    }

    // 5. Floating Chat Form Submit
    if (floatForm) {
        floatForm.addEventListener("submit", async (e) => {
            e.preventDefault();
            if (!floatInput) return;
            const msg = floatInput.value.trim();
            if (!msg) return;
            floatInput.value = "";
            await sendChatMessage(msg);
        });
    }

    // 6. Floating Fast Action Prompt Chips
    document.querySelectorAll(".float-chip-btn").forEach(chip => {
        chip.addEventListener("click", () => {
            const prompt = chip.getAttribute("data-prompt");
            if (prompt) sendChatMessage(prompt);
        });
    });

    // 7. Floating Voice Input
    if (floatMic) {
        if (!('webkitSpeechRecognition' in window) && !('SpeechRecognition' in window)) {
            floatMic.style.display = "none";
        } else {
            const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
            const floatRecog = new SpeechRecognition();
            floatRecog.continuous = false;
            floatRecog.interimResults = false;
            floatRecog.lang = 'en-US';

            floatMic.addEventListener("click", () => {
                if (floatMic.classList.contains("listening")) {
                    floatRecog.stop();
                } else {
                    floatRecog.start();
                    floatMic.classList.add("listening");
                    showToast("Listening... speak your request", "🎤");
                }
            });

            floatRecog.onresult = (event) => {
                const transcript = event.results[0][0].transcript;
                if (floatInput) floatInput.value = transcript;
                floatMic.classList.remove("listening");
                sendChatMessage(transcript);
            };

            floatRecog.onerror = () => floatMic.classList.remove("listening");
            floatRecog.onend = () => floatMic.classList.remove("listening");
        }
    }
}

// ----------------- Reorder Modal & Actions ----------------- //

function openReorderModal(sku, name, recommendedQty) {
    document.getElementById("modalSkuInput").value = sku;
    document.getElementById("modalQtyInput").value = recommendedQty || 20;
    document.getElementById("modalProductText").textContent = `Restock ${name} (${sku}) for [${currentTenantId}]`;
    document.getElementById("restockModal").style.display = "flex";
}

async function executeReorder(sku, quantity) {
    try {
        const res = await tenantFetch("/api/inventory/reorder", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ sku, quantity })
        });
        const data = await res.json();
        
        if (res.ok) {
            showToast(`Restocked ${data.units_ordered} units of ${data.sku}`, "⚡");
            appendMessage(`⚡ **Inventory Restock Complete [${currentTenantId}]:** Added **${data.units_ordered} units** to **${data.product_name}** (${data.sku}). New stock level: **${data.new_stock} units**.`, "bot");
            refreshAllTenantData();
        } else {
            alert(`Reorder failed: ${data.detail || 'Error'}`);
        }
    } catch (err) {
        alert("Failed to submit purchase order.");
    }
}
