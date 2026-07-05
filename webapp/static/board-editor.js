(function () {
  function initEditor(root) {
    var content = root.querySelector(".board-editor-content");
    var hidden = root.querySelector(".board-editor-hidden-textarea");
    var fileInput = root.querySelector(".board-editor-image-input");
    var imageBtn = root.querySelector(".board-editor-image-btn");
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

    content.addEventListener("keyup", saveSelection);
    content.addEventListener("mouseup", saveSelection);

    root.querySelectorAll(".board-editor-btn[data-cmd]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        content.focus();
        document.execCommand(btn.dataset.cmd, false, null);
      });
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
          content.focus();
          restoreSelection();
          document.execCommand("insertHTML", false, '<img src="' + body.url + '">');
        })
        .catch(function (err) {
          alert(err.message);
        })
        .finally(function () {
          fileInput.value = "";
        });
    });

    var form = root.closest("form");
    if (form) {
      form.addEventListener("submit", function (e) {
        hidden.value = content.innerHTML;
        var hasText = content.textContent.trim().length > 0;
        var hasImage = content.querySelectorAll("img").length > 0;
        if (!hasText && !hasImage) {
          e.preventDefault();
          alert("내용을 입력해주세요.");
        }
      });
    }
  }

  document.querySelectorAll(".board-editor").forEach(initEditor);
})();
