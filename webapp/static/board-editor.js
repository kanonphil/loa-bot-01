(function () {
  function escapeHtml(str) {
    var div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
  }

  function initEditor(root) {
    var content = root.querySelector(".board-editor-content");
    var hidden = root.querySelector(".board-editor-hidden-textarea");
    var fileInput = root.querySelector(".board-editor-image-input");
    var imageBtn = root.querySelector(".board-editor-image-btn");
    var linkBtn = root.querySelector(".board-editor-link-btn");
    var sizeSelect = root.querySelector(".board-editor-size-select");
    var colorInput = root.querySelector(".board-editor-color-input");
    var savedRange = null;

    function saveSelection() {
      var sel = window.getSelection();
      if (sel.rangeCount > 0 && content.contains(sel.anchorNode)) {
        savedRange = sel.getRangeAt(0).cloneRange();
      }
    }

    function restoreSelection() {
      var sel = window.getSelection();
      sel.removeAllRanges();
      if (savedRange) {
        sel.addRange(savedRange);
      } else {
        var range = document.createRange();
        range.selectNodeContents(content);
        range.collapse(false);
        sel.addRange(range);
      }
    }

    function wrapImage(img) {
      if (img.closest(".board-editor-image-wrap")) return;
      var wrap = document.createElement("span");
      wrap.className = "board-editor-image-wrap";
      wrap.contentEditable = "false";
      img.replaceWith(wrap);
      wrap.appendChild(img);
      var removeBtn = document.createElement("button");
      removeBtn.type = "button";
      removeBtn.className = "board-editor-image-remove";
      removeBtn.setAttribute("aria-label", "이미지 삭제");
      removeBtn.textContent = "×";
      wrap.appendChild(removeBtn);
    }

    function wrapExistingImages() {
      content.querySelectorAll("img").forEach(wrapImage);
    }

    function insertImage(url) {
      content.focus();
      restoreSelection();
      var sel = window.getSelection();
      if (!sel.rangeCount) return;
      var range = sel.getRangeAt(0);
      range.deleteContents();

      var wrap = document.createElement("span");
      wrap.className = "board-editor-image-wrap";
      wrap.contentEditable = "false";
      var img = document.createElement("img");
      img.src = url;
      var removeBtn = document.createElement("button");
      removeBtn.type = "button";
      removeBtn.className = "board-editor-image-remove";
      removeBtn.setAttribute("aria-label", "이미지 삭제");
      removeBtn.textContent = "×";
      wrap.appendChild(img);
      wrap.appendChild(removeBtn);

      // 사진 바로 아래에 커서가 놓이도록 뒤에 줄바꿈을 넣고 그 뒤로 커서를 이동한다.
      var trailingBr = document.createElement("br");
      var frag = document.createDocumentFragment();
      frag.appendChild(wrap);
      frag.appendChild(trailingBr);
      range.insertNode(frag);

      var newRange = document.createRange();
      newRange.setStartAfter(trailingBr);
      newRange.collapse(true);
      sel.removeAllRanges();
      sel.addRange(newRange);
      saveSelection();
    }

    content.addEventListener("keyup", saveSelection);
    content.addEventListener("mouseup", saveSelection);

    // 사진 첨부는 백스페이스/Delete로 지워지지 않게 막는다 — 오직 × 버튼으로만 삭제.
    content.addEventListener("beforeinput", function (e) {
      if (!e.inputType || e.inputType.indexOf("delete") !== 0) return;
      var wraps = content.querySelectorAll(".board-editor-image-wrap");
      if (!wraps.length) return;
      if (typeof e.getTargetRanges === "function") {
        var targetRanges = e.getTargetRanges();
        for (var i = 0; i < targetRanges.length; i++) {
          for (var j = 0; j < wraps.length; j++) {
            if (targetRanges[i].intersectsNode(wraps[j])) {
              e.preventDefault();
              return;
            }
          }
        }
      }
    });

    content.addEventListener("click", function (e) {
      if (e.target.classList.contains("board-editor-image-remove")) {
        e.preventDefault();
        var wrap = e.target.closest(".board-editor-image-wrap");
        if (wrap) wrap.remove();
      }
    });

    root.querySelectorAll(".board-editor-btn[data-cmd]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        content.focus();
        document.execCommand(btn.dataset.cmd, false, null);
      });
    });

    linkBtn.addEventListener("click", function () {
      content.focus();
      restoreSelection();
      var sel = window.getSelection();
      var hasSelection = sel && !sel.isCollapsed && content.contains(sel.anchorNode);

      var url = prompt("연결할 주소를 입력하세요 (https://...)");
      if (!url) return;
      url = url.trim();
      if (!url) return;
      if (!/^https?:\/\//i.test(url)) {
        url = "https://" + url;
      }
      var safeUrl = url.replace(/"/g, "&quot;");

      if (hasSelection) {
        document.execCommand("createLink", false, url);
        var anchor = sel.anchorNode && sel.anchorNode.parentElement && sel.anchorNode.parentElement.closest("a");
        if (anchor) {
          anchor.setAttribute("target", "_blank");
          anchor.setAttribute("rel", "noopener noreferrer");
        }
      } else {
        var text = prompt("링크에 표시할 텍스트를 입력하세요", url);
        if (text === null) return;
        var label = text.trim() || url;
        document.execCommand(
          "insertHTML",
          false,
          '<a href="' + safeUrl + '" target="_blank" rel="noopener noreferrer">' + escapeHtml(label) + "</a>"
        );
      }
    });

    function applyStyleToSelection(prop, value) {
      content.focus();
      restoreSelection();
      var sel = window.getSelection();
      if (!sel.rangeCount || sel.isCollapsed || !content.contains(sel.anchorNode)) {
        alert("먼저 서식을 적용할 텍스트를 선택해주세요.");
        return;
      }
      var range = sel.getRangeAt(0);
      var span = document.createElement("span");
      span.style[prop] = value;
      try {
        range.surroundContents(span);
      } catch (e) {
        var frag = range.extractContents();
        span.appendChild(frag);
        range.insertNode(span);
      }
      sel.removeAllRanges();
      var newRange = document.createRange();
      newRange.selectNodeContents(span);
      sel.addRange(newRange);
      saveSelection();
    }

    sizeSelect.addEventListener("change", function () {
      if (!sizeSelect.value) return;
      applyStyleToSelection("fontSize", sizeSelect.value);
      sizeSelect.value = "";
    });

    colorInput.addEventListener("change", function () {
      applyStyleToSelection("color", colorInput.value);
    });

    imageBtn.addEventListener("click", function () {
      saveSelection();
      fileInput.click();
    });

    fileInput.addEventListener("change", function () {
      var file = fileInput.files[0];
      if (!file) return;
      var data = new FormData();
      data.append("file", file);
      fetch("/board/upload-image", { method: "POST", body: data })
        .then(function (res) {
          if (!res.ok) {
            return res.json().then(function (body) {
              throw new Error((body && body.detail) || "이미지 업로드에 실패했습니다.");
            });
          }
          return res.json();
        })
        .then(function (body) {
          insertImage(body.url);
        })
        .catch(function (err) {
          alert(err.message);
        })
        .finally(function () {
          fileInput.value = "";
        });
    });

    function getCleanHtml() {
      var clone = content.cloneNode(true);
      clone.querySelectorAll(".board-editor-image-wrap").forEach(function (wrap) {
        var img = wrap.querySelector("img");
        if (img) {
          wrap.replaceWith(img);
        } else {
          wrap.remove();
        }
      });
      return clone.innerHTML;
    }

    var form = root.closest("form");
    if (form) {
      form.addEventListener("submit", function (e) {
        hidden.value = getCleanHtml();
        var hasText = content.textContent.trim().length > 0;
        var hasImage = content.querySelectorAll("img").length > 0;
        if (!hasText && !hasImage) {
          e.preventDefault();
          alert("내용을 입력해주세요.");
        }
      });
    }

    wrapExistingImages();
  }

  document.querySelectorAll(".board-editor").forEach(initEditor);
})();
