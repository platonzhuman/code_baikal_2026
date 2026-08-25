"""Общие фикстуры/настройка тестов.

Тесты не должны ходить в реальный LLM и ждать внешние API: принудительно
включаем mock-режим генератора/судьи (переменная окружения имеет приоритет
над .env в pydantic-settings).
"""
import os

os.environ["LLM_MODE"] = "mock"
os.environ["LLM_API_KEY"] = ""
os.environ["LLM_MODEL"] = ""