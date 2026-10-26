"""Агентный цикл: мозг, инструменты, события и стоп-кран."""

from __future__ import annotations

import threading
import time
from typing import Any, Mapping, Sequence

from pcagent import llm
from pcagent.agent import prompts
from pcagent.events import KIND_LOG, Event, kill_switch
from pcagent import vision

#: Подпись к снимку. Нужна не для смысла, а чтобы сообщение с картинкой
#: содержало текст: без него провайдер отбрасывает изображение.
SCREENSHOT_CAPTION = "Снимок экрана:"
from pcagent.interfaces import RunResult
from pcagent.tools.base import ToolContext

class AgentSession:
    """Одна сессия агента: выполняет задачу шаг за шагом."""

    def __init__(
        self,
        config: Any,
        registry: Any,
        policy: Any,
        bus: Any,
        logger: Any = None,
        brain: Any = None,
        screen: Any = None,
    ) -> None:
        self.config = config
        self.registry = registry
        self.policy = policy
        self.bus = bus
        self.logger = logger
        self.screen = screen
        self._brain = brain
        self._running = False
        self._stop_requested = False
        self._lock = threading.Lock()

    # --- публичное состояние -----------------------------------------
    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def brain(self) -> Any:
        """Мозг создаётся лениво: stub-режим не требует ключа API."""
        if self._brain is None:
            if getattr(self.config, "stub_mode", False):
                from pcagent.stub_brain import StubBrain

                self._brain = StubBrain(logger=self.logger)
            else:
                # Запасной мозг: официальный SDK Google. Любой другой
                # провайдер подставляется вызывающим кодом через brain=.
                self._brain = llm.GoogleBrain(self.config, logger=self.logger)
        return self._brain

    @brain.setter
    def brain(self, value: Any) -> None:
        self._brain = value

    @property
    def model_name(self) -> str:
        """Имя модели, которой реально отвечал мозг."""
        return str(getattr(self._brain, "active_model", getattr(self.config, "model", "")) or "")

    def stop(self) -> None:
        """Мягкая остановка: цикл завершится на ближайшей проверке."""
        self._stop_requested = True
        self._log("stop_requested", {})

    # --- основной сценарий -------------------------------------------
    def run_task(self, task: str) -> RunResult:
        """Выполнить задачу и вернуть результат."""
        with self._lock:
            if self._running:
                return RunResult(success=False, error="сессия уже выполняет задачу")
            self._running = True
            self._stop_requested = False
        result = RunResult(success=False, error="задача не выполнялась")
        try:
            result = self._run(str(task or "").strip())
        except Exception as exc:  # noqa: BLE001 - наружу отдаём RunResult, а не трейс
            message = f"Непредвиденная ошибка агента: {type(exc).__name__}: {exc}"
            self._publish(Event.error(message))
            self._log("loop_crash", {"error": message})
            result = RunResult(success=False, error=message)
        finally:
            with self._lock:
                self._running = False
            result.transcript_path = self._transcript_path()
            self._publish(Event.done(result.as_dict()))
            self._log("run_finished", result.as_dict())
        return result

    # ------------------------------------------------------------------
    def _run(self, task: str) -> RunResult:
        if not task:
            return RunResult(success=False, error="пустая задача")

        screen = self._ensure_screen()
        declarations = self._declarations()
        instruction = prompts.system_prompt(self.config, self._tool_names())
        ctx = ToolContext(
            config=self.config,
            screen=screen,
            policy=self.policy,
            logger=self.logger,
            bus=self.bus,
            dry_run=bool(getattr(self.config, "dry_run", False) or getattr(self.policy, "dry_run", False)),
            registry=self.registry,
        )
        history: list[Any] = [self._initial_content(task, screen, ctx)]
        actions: list[dict[str, Any]] = []
        max_steps = int(getattr(self.config, "max_steps", 25) or 25)
        step = 0
        self._log("run_started", {"task": task, "model": getattr(self.config, "model", ""), "max_steps": max_steps})
        self._publish(Event.status(f"Задача принята, модель {getattr(self.config, 'model', '')}"))

        while step < max_steps:
            if self._stop_requested or kill_switch.triggered:
                self._publish(Event.status("Остановлено пользователем"))
                return RunResult(
                    success=False,
                    steps=step,
                    error="остановлено пользователем (kill switch)",
                )

            step += 1
            self._publish(Event.step(step))
            self._log("step", {"number": step})

            response, error = self._generate(history, declarations, instruction)
            if response is None:
                return RunResult(success=False, steps=step, error=error)

            parts = llm.extract_parts(response)
            content = llm.response_content(response)
            if content is not None:
                history.append(content)

            answer = llm.extract_text(parts)
            reasoning = llm.extract_thoughts(response)
            thought_text = "\n".join(item for item in (reasoning, answer) if item).strip()
            if thought_text:
                self._publish(Event.thought(thought_text))
                self._log("thought", {"step": step, "text": thought_text})

            calls = llm.extract_calls(parts)
            if not calls:
                if answer:
                    self._publish(Event.status("Модель ответила без вызова инструментов"))
                    return RunResult(success=True, steps=step, final_text=answer)
                message = "модель не вернула ни действий, ни ответа (возможно, сработал фильтр безопасности)"
                self._publish(Event.error(message))
                return RunResult(success=False, steps=step, error=message)

            responses: list[dict[str, Any]] = []
            images: list[dict[str, Any]] = []
            finished: RunResult | None = None

            for call in calls:
                name = str(call.get("name") or "").strip()
                args = dict(call.get("args") or {})
                call_id = call.get("id")

                if name == prompts.FINISH_TOOL:
                    finished = self._handle_finish(ctx, args, step, actions)
                    continue

                self._publish(Event.action(name, args))
                self._log("action", {"step": step, "name": name, "args": args})
                result = self.registry.execute(ctx, name, args)
                self._publish(Event.result(name, result.ok, result.summary, result.data))
                self._log(
                    "result",
                    {"step": step, "name": name, "ok": result.ok, "summary": result.summary},
                )
                actions.append(
                    {
                        "step": step,
                        "tool": name,
                        "args": args,
                        "ok": bool(result.ok),
                        "summary": result.summary,
                    }
                )
                responses.append(
                    {
                        "type": "function_response",
                        "name": name,
                        "response": llm.truncate_result(
                            result.model_response(),
                            int(getattr(self.config, "max_tool_result_chars", 6000) or 6000),
                        ),
                        "id": call_id,
                    }
                )
                for shot in result.images or []:
                    part = llm.screenshot_part(shot)
                    if part is None:
                        continue
                    # Инструменты мыши/окон переводят координаты по геометрии
                    # именно того снимка, который увидела модель.
                    self._remember_screenshot(ctx, shot)
                    self._publish_image(shot)
                    images.append(part)

            if responses or images:
                history.append(
                    llm.message_to_content({"role": "user", "parts": [*responses]})
                )
                # Снимок уходит ОТДЕЛЬНЫМ сообщением и всегда с текстом.
                # Провайдеры OpenAI-совместимого формата молча отбрасывают
                # сообщение, состоящее только из image_url: модель получает
                # историю без картинки и отвечает "изображение не пришло".
                # Проверено на реальном прогоне: картинка без текста не
                # доходит, картинка с подписью доходит.
                if images:
                    caption = {"type": "text", "text": SCREENSHOT_CAPTION}
                    history.append(
                        llm.message_to_content({"role": "user", "parts": [caption, *images]})
                    )
                self._prune(history)

            if finished is not None:
                finished.steps = step
                finished.actions = actions
                return finished

            if actions and step < max_steps:
                self._pause([str(item.get("tool") or "") for item in actions])

        message = "превышен лимит шагов"
        self._publish(Event.error(message))
        self._log("step_limit", {"steps": step})
        return RunResult(success=False, steps=step, error=message, actions=actions)

    # ------------------------------------------------------------------
    def _generate(
        self,
        history: list[Any],
        declarations: Sequence[Mapping[str, Any]],
        instruction: str,
    ) -> tuple[Any, str | None]:
        """Запрос к мозгу с одной повторной попыткой без изображений."""
        try:
            return self.brain.generate(history, declarations, system_instruction=instruction), None
        except Exception as exc:  # noqa: BLE001 - сеть, лимиты, ключ
            message = f"Ошибка запроса к модели: {exc}"
            self._publish(Event.error(message))
            self._log("llm_error", {"error": str(exc)[:800]})
            if llm.count_images(history) == 0:
                return None, message

        removed = llm.strip_images(history)
        self._publish(
            Event(KIND_LOG, f"Повторный запрос без изображений (убрано снимков: {removed})")
        )
        self._log("llm_retry_without_images", {"removed": removed})
        try:
            return self.brain.generate(history, declarations, system_instruction=instruction), None
        except Exception as exc:  # noqa: BLE001
            message = f"Повторный запрос к модели не удался: {exc}"
            self._publish(Event.error(message))
            self._log("llm_error", {"error": str(exc)[:800], "retry": True})
            return None, message

    # ------------------------------------------------------------------
    def _initial_content(self, task: str, screen: Any, ctx: Any = None) -> Any:
        """Первое сообщение: задача, снимок экрана и дерево UIA."""
        uia = self._uia_tree(screen)
        text = prompts.initial_user_message(task, uia_tree=uia)
        parts: list[dict[str, Any]] = [{"type": "text", "text": text}]
        shot = self._capture(screen, ctx)
        if shot is not None:
            parts.append(
                {
                    "type": "image",
                    "data": getattr(shot, "image_bytes", b""),
                    "mime_type": getattr(shot, "mime_type", "image/jpeg"),
                }
            )
        return llm.message_to_content({"role": "user", "parts": parts})

    def _capture(self, screen: Any, ctx: Any = None) -> Any | None:
        """Снимок экрана: публикует KIND_IMAGE и запоминает геометрию в ctx."""
        if screen is None:
            return None
        try:
            shot = screen.capture(
                monitor=getattr(self.config, "monitor", 0),
                max_width=getattr(self.config, "screenshot_max_width", 1440),
                fmt=getattr(self.config, "screenshot_format", "jpeg"),
                quality=getattr(self.config, "screenshot_quality", 70),
            )
        except Exception as exc:  # noqa: BLE001 - без снимка цикл тоже работает
            self._log("capture_error", {"error": str(exc)[:400]})
            self._publish(Event(KIND_LOG, f"Не удалось снять экран: {exc}"))
            return None
        self._remember_screenshot(ctx, shot)
        self._publish_image(shot)
        return shot

    def _remember_screenshot(self, ctx: Any, shot: Any) -> None:
        """Запомнить последний снимок в контексте инструментов."""
        if ctx is None or shot is None:
            return
        remember = getattr(ctx, "remember_screenshot", None)
        if callable(remember):
            try:
                remember(shot)
            except Exception as exc:  # noqa: BLE001 - не ломаем цикл
                self._log("remember_screenshot_error", {"error": str(exc)[:300]})
            return
        try:
            ctx.last_screenshot = shot
        except Exception:  # noqa: BLE001
            pass

    def _publish_image(self, shot: Any) -> None:
        if shot is None:
            return
        info: dict[str, Any] = {}
        as_dict = getattr(shot, "as_dict", None)
        if callable(as_dict):
            try:
                info = dict(as_dict())
            except Exception:  # noqa: BLE001
                info = {}
        self._publish(
            Event.image(getattr(shot, "path", None), getattr(shot, "image_bytes", None), **info)
        )
        self._log("image", {"bytes": len(getattr(shot, "image_bytes", b"") or b""), **info})

    def _uia_tree(self, screen: Any) -> str:
        """Дерево UI Automation (пустая строка при любой проблеме)."""
        if screen is None or not getattr(self.config, "include_uia_tree", True):
            return ""
        try:
            tree = screen.uia_tree(max_nodes=getattr(self.config, "uia_max_nodes", 250))
        except Exception as exc:  # noqa: BLE001
            self._log("uia_error", {"error": str(exc)[:400]})
            return ""
        return str(tree or "")

    def _ensure_screen(self) -> Any:
        """Сервис экрана: переданный снаружи или собранный из pcagent.capture."""
        if self.screen is not None:
            return self.screen
        try:
            from pcagent.capture import Screen

            self.screen = Screen(self.config)
        except Exception as exc:  # noqa: BLE001 - модуль ещё может быть не готов
            self._log("screen_unavailable", {"error": str(exc)[:400]})
            self._publish(Event(KIND_LOG, f"Сервис экрана недоступен: {exc}"))
            self.screen = None
        return self.screen

    def _declarations(self) -> list[dict[str, Any]]:
        """Декларации инструментов: реестр + встроенный finish_task."""
        declarations: list[dict[str, Any]] = []
        names: set[str] = set()
        try:
            for item in self.registry.declarations() if self.registry is not None else []:
                declarations.append(dict(item))
                names.add(str(item.get("name") or ""))
        except Exception as exc:  # noqa: BLE001
            self._log("declarations_error", {"error": str(exc)[:400]})
        if prompts.FINISH_TOOL not in names:
            declarations.append(prompts.finish_task_declaration())
        return declarations

    def _tool_names(self) -> list[str]:
        try:
            return list(self.registry.names()) if self.registry is not None else []
        except Exception:  # noqa: BLE001
            return []

    def _handle_finish(
        self,
        ctx: ToolContext,
        args: Mapping[str, Any],
        step: int,
        actions: list[dict[str, Any]],
    ) -> RunResult:
        """Обработать finish_task: остановить цикл и собрать RunResult."""
        name = prompts.FINISH_TOOL
        payload = dict(args or {})
        self._publish(Event.action(name, payload))
        self._log("action", {"step": step, "name": name, "args": payload})

        if self.registry is not None and name in self.registry:
            result = self.registry.execute(ctx, name, payload)
            self._publish(Event.result(name, result.ok, result.summary, result.data))
        else:
            self._publish(Event.result(name, True, "Задача завершена", {}))

        summary = str(payload.get("summary") or "").strip() or "Задача завершена."
        success = payload.get("success")
        success = True if success is None else bool(success)
        actions.append(
            {"step": step, "tool": name, "args": payload, "ok": success, "summary": summary}
        )
        self._publish(Event.status(summary))
        self._log("finish_task", {"step": step, "success": success, "summary": summary})
        return RunResult(success=success, final_text=summary)

    def _prune(self, history: list[Any]) -> None:
        """Оставить в истории только последние снимки."""
        # Старые результаты инструментов тоже раздувают запрос: каждый
        # обход UIA-дерева это 8-12 КБ. Оставляем последние N.
        try:
            kept = int(getattr(self.config, "keep_tool_results", 6) or 6)
            dropped = llm.prune_history_results(history, kept)
            if dropped:
                self._log("results_pruned", {"removed": dropped, "keep": kept})
        except Exception as exc:  # noqa: BLE001 - обрезка не должна ломать цикл
            self._log("prune_results_error", {"error": str(exc)[:300]})
        keep = getattr(self.config, "max_history_images", 3)
        try:
            removed = llm.prune_history_images(history, keep)
        except Exception as exc:  # noqa: BLE001
            self._log("prune_error", {"error": str(exc)[:400]})
            return
        if removed:
            self._log("history_pruned", {"removed": removed, "keep": keep})

    def _pause(self, action_names: list[str] | None = None) -> None:
        """Дождаться, пока интерфейс успокоится, вместо фиксированного сна.

        Раньше здесь был time.sleep(action_delay): 0.7 с после КАЖДОГО шага,
        даже если на экране ничего не менялось. Теперь кадр сравнивается с
        предыдущим, и ожидание заканчивается, как только картинка перестала
        меняться. Верхняя граница - тот же action_delay, поэтому поведение
        не может стать медленнее, чем было.

        Если действие не влияет на интерфейс (run_script, list_windows,
        get_system_info и т.п.), ждать нечего: инструмент уже вернул
        управление по завершении.
        """
        delay = float(getattr(self.config, "action_delay", 0.0) or 0.0)
        if delay <= 0:
            return

        # Только действия, после которых экран реально перерисовывается.
        names = {str(name) for name in (action_names or [])}
        if names and not (names & vision.UI_ACTION_TOOLS):
            self._log("pause_skipped", {"reason": "no_ui_action", "actions": sorted(names)})
            return

        screen = getattr(self, "screen", None)
        detector = vision.SettleDetector(screen, max_wait_s=delay) if screen is not None else None
        if detector is None:
            time.sleep(delay)
            return

        result = detector.wait()
        self._log("pause", result.as_dict())

    def _transcript_path(self) -> str | None:
        path = getattr(self.logger, "path", None)
        return str(path) if path else None

    def _publish(self, event: Event) -> None:
        if self.bus is None:
            return
        try:
            self.bus.publish(event)
        except Exception:  # noqa: BLE001 - шина не должна ломать цикл
            pass

    def _log(self, kind: str, payload: dict[str, Any] | None = None) -> None:
        if self.logger is None:
            return
        try:
            self.logger.log(kind, payload)
        except Exception:  # noqa: BLE001
            pass
