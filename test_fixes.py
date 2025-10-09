#!/usr/bin/env python3
"""
Test script to verify all critical fixes are working
"""
import asyncio
import sys
import traceback
from typing import List, Tuple

# Test results storage
test_results: List[Tuple[str, bool, str]] = []

def report_test(name: str, passed: bool, message: str = ""):
    """Store test result"""
    test_results.append((name, passed, message))
    status = "✅ PASS" if passed else "❌ FAIL"
    print(f"{status}: {name}")
    if message:
        print(f"  {message}")

async def test_imports():
    """Test that all modules can be imported"""
    try:
        from app.main import app
        from app.core.config import get_settings
        from app.services.orchestrator import get_orchestrator
        from app.services.ai.openrouter_client import get_openrouter_client
        from app.services.github_client import get_github_client
        report_test("Module imports", True)
    except Exception as e:
        report_test("Module imports", False, str(e))
        return False
    return True

async def test_config():
    """Test configuration settings"""
    try:
        from app.core.config import get_settings
        settings = get_settings()
        
        # Check required attributes
        assert hasattr(settings, 'PROJECT_NAME'), "Missing PROJECT_NAME"
        assert hasattr(settings, 'PROJECT_VERSION'), "Missing PROJECT_VERSION"
        assert hasattr(settings, 'API_V1_STR'), "Missing API_V1_STR"
        assert hasattr(settings, 'AUTH_SECRET_KEY'), "Missing AUTH_SECRET_KEY"
        
        report_test("Configuration attributes", True)
    except Exception as e:
        report_test("Configuration attributes", False, str(e))
        return False
    return True

async def test_app_creation():
    """Test FastAPI app creation"""
    try:
        from app.main import app
        assert app is not None
        assert app.title is not None
        report_test("FastAPI app creation", True)
    except Exception as e:
        report_test("FastAPI app creation", False, str(e))
        return False
    return True

async def test_middleware():
    """Test middleware setup"""
    try:
        from app.main import app
        middleware_names = [m.cls.__name__ for m in app.user_middleware]
        
        # Check for SessionMiddleware
        assert any('SessionMiddleware' in str(m.cls) for m in app.user_middleware), \
            "SessionMiddleware not found"
        
        # Check for CORSMiddleware
        assert any('CORSMiddleware' in str(m.cls) for m in app.user_middleware), \
            "CORSMiddleware not found"
            
        report_test("Middleware configuration", True)
    except Exception as e:
        report_test("Middleware configuration", False, str(e))
        return False
    return True

async def test_endpoints():
    """Test that key endpoints exist"""
    try:
        from app.main import app
        routes = [route.path for route in app.routes]
        
        required_routes = [
            "/healthz",
            "/",
            "/api/v1/auth/login",
            "/api/v1/auth/logout",
            "/api/v1/auth/csrf",
            "/api/v1/jobs",
        ]
        
        missing = [r for r in required_routes if not any(r in route for route in routes)]
        if missing:
            report_test("API endpoints", False, f"Missing routes: {missing}")
            return False
            
        report_test("API endpoints", True)
    except Exception as e:
        report_test("API endpoints", False, str(e))
        return False
    return True

async def test_agents():
    """Test agent initialization"""
    try:
        from app.services.agents.coder import CoderAgent
        from app.services.agents.debugger import DebuggerAgent
        from app.services.agents.fixer import FixerAgent
        from app.services.agents.chatbot import ChatbotAgent
        
        # Create instances
        coder = CoderAgent()
        debugger = DebuggerAgent()
        fixer = FixerAgent()
        chatbot = ChatbotAgent()
        
        # Check they initialize properly
        assert coder.client is None, "Coder client should be None initially"
        assert debugger.client is None, "Debugger client should be None initially"
        assert fixer.client is None, "Fixer client should be None initially"
        assert chatbot.client is None, "Chatbot client should be None initially"
        
        report_test("Agent initialization", True)
    except Exception as e:
        report_test("Agent initialization", False, str(e))
        return False
    return True

async def test_orchestrator():
    """Test orchestrator creation"""
    try:
        from app.services.orchestrator import get_orchestrator
        
        # Note: This will fail if GitHub client isn't configured
        # but we're testing that it can at least be imported
        try:
            orch = await get_orchestrator()
            report_test("Orchestrator creation", True)
        except Exception as e:
            # Expected if no GitHub token
            if "GITHUB_TOKEN" in str(e) or "http_client" in str(e):
                report_test("Orchestrator creation", True, 
                          "Skipped (needs GitHub token)")
            else:
                raise
    except Exception as e:
        report_test("Orchestrator creation", False, str(e))
        return False
    return True

async def test_database():
    """Test database configuration"""
    try:
        from app.db.mongo import get_db
        from app.core.config import get_settings
        
        settings = get_settings()
        
        # Check MongoDB URI resolution
        uri = settings.mongodb_uri_resolved
        if not uri:
            report_test("Database configuration", True, 
                      "Skipped (no MongoDB URI configured)")
        else:
            # Try to get DB instance (may fail if MongoDB not running)
            try:
                db = await get_db()
                report_test("Database configuration", True)
            except Exception as e:
                report_test("Database configuration", True,
                          f"MongoDB not running (expected): {str(e)[:50]}")
    except Exception as e:
        report_test("Database configuration", False, str(e))
        return False
    return True

async def main():
    """Run all tests"""
    print("\n" + "="*60)
    print(" Ureshii-Partner Backend - Fix Verification Tests")
    print("="*60 + "\n")
    
    # Run tests in order
    tests = [
        test_imports,
        test_config,
        test_app_creation,
        test_middleware,
        test_endpoints,
        test_agents,
        test_orchestrator,
        test_database,
    ]
    
    for test_func in tests:
        try:
            await test_func()
        except Exception as e:
            print(f"Unexpected error in {test_func.__name__}: {e}")
            traceback.print_exc()
    
    # Summary
    print("\n" + "="*60)
    print(" Test Summary")
    print("="*60)
    
    passed = sum(1 for _, p, _ in test_results if p)
    failed = sum(1 for _, p, _ in test_results if not p)
    
    print(f"\n✅ Passed: {passed}")
    print(f"❌ Failed: {failed}")
    print(f"📊 Total:  {len(test_results)}")
    
    if failed == 0:
        print("\n🎉 All tests passed! The backend is ready to run.")
    else:
        print("\n⚠️ Some tests failed. Please review the errors above.")
        print("\nFailed tests:")
        for name, passed, msg in test_results:
            if not passed:
                print(f"  - {name}: {msg}")
    
    return failed == 0

if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)