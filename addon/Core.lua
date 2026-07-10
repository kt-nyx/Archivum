local ADDON_NAME = ...
local LoreCompanion = {}
_G.LoreCompanion = LoreCompanion

LoreCompanion.state = {
  currentPageType = "zone",
  currentPageId = nil,
  history = {},
}

local function ensureFrame()
  if LoreCompanion.frame then
    return LoreCompanion.frame
  end
  local frame = CreateFrame("Frame", "LoreCompanionFrame", UIParent, "BasicFrameTemplateWithInset")
  frame:SetSize(760, 520)
  frame:SetPoint("CENTER")
  frame:Hide()
  frame.title = frame:CreateFontString(nil, "OVERLAY", "GameFontHighlight")
  frame.title:SetPoint("LEFT", frame.TitleBg, "LEFT", 8, 0)
  frame.title:SetText("Lore Companion")
  LoreCompanion.frame = frame
  return frame
end

local function ensureBodyWidgets(frame)
  if frame.body then
    return
  end
  frame.body = frame:CreateFontString(nil, "OVERLAY", "GameFontNormal")
  frame.body:SetPoint("TOPLEFT", frame, "TOPLEFT", 16, -40)
  frame.body:SetWidth(720)
  frame.body:SetJustifyH("LEFT")

  frame.back = CreateFrame("Button", nil, frame, "UIPanelButtonTemplate")
  frame.back:SetSize(90, 24)
  frame.back:SetPoint("BOTTOMLEFT", frame, "BOTTOMLEFT", 12, 12)
  frame.back:SetText("Back")
  frame.back:SetScript("OnClick", function()
    local prev = table.remove(LoreCompanion.state.history)
    if prev then
      LoreCompanion:OpenPage(prev.pageType, prev.pageId, false)
    end
  end)

  frame.wiki = CreateFrame("Button", nil, frame, "UIPanelButtonTemplate")
  frame.wiki:SetSize(120, 24)
  frame.wiki:SetPoint("BOTTOMRIGHT", frame, "BOTTOMRIGHT", -12, 12)
  frame.wiki:SetText("Wiki Link")
  frame.wiki:SetScript("OnClick", function()
    if LoreCompanion.state.currentWikiUrl then
      LoreCompanion:ShowWikiCopyModal(LoreCompanion.state.currentWikiUrl)
    end
  end)
end

function LoreCompanion:ShowWikiCopyModal(url)
  if not self.copyFrame then
    local copyFrame = CreateFrame("Frame", "LoreCompanionCopyModal", UIParent, "BasicFrameTemplateWithInset")
    copyFrame:SetSize(560, 140)
    copyFrame:SetPoint("CENTER")
    copyFrame:Hide()
    copyFrame.title = copyFrame:CreateFontString(nil, "OVERLAY", "GameFontHighlight")
    copyFrame.title:SetPoint("LEFT", copyFrame.TitleBg, "LEFT", 8, 0)
    copyFrame.title:SetText("Copy Warcraft Wiki Link")
    copyFrame.edit = CreateFrame("EditBox", nil, copyFrame, "InputBoxTemplate")
    copyFrame.edit:SetSize(500, 28)
    copyFrame.edit:SetPoint("TOP", copyFrame, "TOP", 0, -46)
    copyFrame.edit:SetAutoFocus(true)
    copyFrame.edit:SetScript("OnEscapePressed", function() copyFrame:Hide() end)
    copyFrame.desc = copyFrame:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
    copyFrame.desc:SetPoint("TOPLEFT", copyFrame.edit, "BOTTOMLEFT", 0, -10)
    copyFrame.desc:SetText("Press Ctrl+C to copy, then close.")
    copyFrame.close = CreateFrame("Button", nil, copyFrame, "UIPanelButtonTemplate")
    copyFrame.close:SetSize(90, 22)
    copyFrame.close:SetPoint("BOTTOM", copyFrame, "BOTTOM", 0, 12)
    copyFrame.close:SetText("Close")
    copyFrame.close:SetScript("OnClick", function() copyFrame:Hide() end)
    self.copyFrame = copyFrame
  end
  self.copyFrame.edit:SetText(url)
  self.copyFrame:Show()
  self.copyFrame.edit:SetFocus()
  self.copyFrame.edit:HighlightText()
end

function LoreCompanion:OpenPage(pageType, pageId, pushHistory)
  local frame = ensureFrame()
  ensureBodyWidgets(frame)
  if pushHistory ~= false and self.state.currentPageId then
    table.insert(self.state.history, {
      pageType = self.state.currentPageType,
      pageId = self.state.currentPageId,
    })
  end
  self.state.currentPageType = pageType
  self.state.currentPageId = pageId
  self.state.currentWikiUrl = "https://warcraft.wiki.gg/wiki/" .. (pageId or "")
  frame.title:SetText("Lore Companion - " .. (pageType or "page"))
  frame.body:SetText("Page: " .. (pageId or "unknown") .. "\n\nData integration hook point.")
  frame:Show()
end

SLASH_LORECOMPANION1 = "/lorecompanion"
SLASH_LORECOMPANION2 = "/lore"
SlashCmdList["LORECOMPANION"] = function(msg)
  local pageId = msg and msg:match("^%s*(.-)%s*$") or ""
  if pageId == "" then
    local frame = ensureFrame()
    ensureBodyWidgets(frame)
    LoreCompanion.state.currentPageId = nil
    LoreCompanion.state.currentWikiUrl = nil
    frame.title:SetText("Lore Companion")
    frame.body:SetText("Use /lore <zone-or-instance-id> to open a page.")
    frame:Show()
    return
  end
  LoreCompanion:OpenPage("zone", pageId, false)
end
