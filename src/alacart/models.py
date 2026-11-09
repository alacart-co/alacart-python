"""The shapes that the Alacart API returns and takes.

Each response class has a `from_dict` that reads the API's JSON. It ignores fields it does not
know, because later releases of the API may add fields. Fields with a fixed set of values, such
as a meal's `type`, are plain strings, because later releases may also add values.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from ._parse import (
    as_mapping,
    as_str,
    get_bool,
    get_int,
    get_list,
    get_objects,
    get_opt_float,
    get_opt_int,
    get_opt_str,
    get_opt_time,
    get_str,
    get_time,
)
from ._validate import check_id, check_strings


class ItemOrder(StrEnum):
    """The orders that `get_items` can return items in."""

    ADDED = "added"
    """The most recently added items first."""

    MANUAL = "manual"
    """The order the user set by hand. It needs a list id."""


class RecipeSort(StrEnum):
    """The sort orders of a recipe box search."""

    RELEVANCE = "relevance"
    NEWEST = "newest"
    ALPHABETICAL = "alphabetical"
    MOST_COOKED = "most_cooked"
    LEAST_COOKED = "least_cooked"
    LATEST_COOKED = "latest_cooked"
    EARLIEST_COOKED = "earliest_cooked"
    SHORTEST_COOKING_TIME = "shortest_cooking_time"
    HIGHEST_GRADE = "highest_grade"
    RANDOM = "random"


class MealType(StrEnum):
    """The meal types that v1 knows. A meal can also have a type that a later release adds."""

    RECIPE = "recipe"
    """A meal that cooks a recipe from the recipe box."""

    TITLE = "title"
    """A meal with a title and no recipe."""


class RecipeImportFailure(StrEnum):
    """The reasons that `RecipeImportFailedError.reason` can give."""

    SITE_NOT_SUPPORTED = "site_not_supported"
    SITE_DENIES_IMPORT = "site_denies_import"
    UNREADABLE_PAGE = "unreadable_page"
    MULTIPLE_RECIPES_FOUND = "multiple_recipes_found"
    NO_RECIPE_FOUND = "no_recipe_found"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class Me:
    """The account that the token acts for."""

    id: str
    """A stable id for the person, the same across all of their sign-in methods."""
    display_name: str | None
    """The user's own name from their profile, or None when they have given none."""
    premium_expires_at: datetime | None
    """When the purchase behind premium ends, or None when no purchase gives an end date."""
    is_family_premium: bool
    """True when the purchase behind the account's premium is a family purchase."""

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Me:
        return cls(
            id=get_str(data, "id"),
            display_name=get_opt_str(data, "displayName"),
            premium_expires_at=get_opt_time(data, "premiumExpiresAt"),
            is_family_premium=get_bool(data, "isFamilyPremium"),
        )


@dataclass(frozen=True, slots=True)
class ItemList:
    """A shopping list."""

    id: str
    name: str
    is_default: bool
    """True for the list that items go to when the app names no list."""
    is_private: bool
    """False when everyone who shares the user's account sees the list.

    True for the user's own private lists, and for lists that another person shares with the
    user.
    """

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ItemList:
        return cls(
            id=get_str(data, "id"),
            name=get_str(data, "name"),
            is_default=get_bool(data, "isDefault"),
            is_private=get_bool(data, "isPrivate"),
        )


@dataclass(frozen=True, slots=True)
class ItemLists:
    """The user's shopping lists, with the ETag of the answer."""

    item_lists: list[ItemList]
    etag: str | None
    """Pass it to the next `get_item_lists` call, which then returns None if nothing changed."""


@dataclass(frozen=True, slots=True)
class Item:
    """An item on a shopping list.

    A checked item that is not permanent leaves the list 180 minutes after it was checked. A
    permanent item always reports `is_checked` as False.
    """

    id: str
    list_id: str
    text: str
    """The item as the user wrote it, such as `2 l mjölk`."""
    is_checked: bool
    is_permanent: bool
    """True when the item stays on the list after shopping."""
    added_at: datetime
    updated_at: datetime

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Item:
        return cls(
            id=get_str(data, "id"),
            list_id=get_str(data, "listId"),
            text=get_str(data, "text"),
            is_checked=get_bool(data, "isChecked"),
            is_permanent=get_bool(data, "isPermanent"),
            added_at=get_time(data, "addedAt"),
            updated_at=get_time(data, "updatedAt"),
        )


@dataclass(frozen=True, slots=True)
class Items:
    """Items from `get_items`, with the ETag of the answer."""

    items: list[Item]
    etag: str | None
    """Pass it to the next `get_items` call with the same arguments.

    That call then returns None if nothing changed.
    """


@dataclass(frozen=True, slots=True)
class AddedItem:
    """The answer for one text that `add_items` added."""

    item: Item
    """The item the text became, or the existing item it merged into."""
    merged_into_existing: bool
    """True when the text merged into an item that was already on the list."""

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> AddedItem:
        return cls(
            item=Item.from_dict(data),
            merged_into_existing=get_bool(data, "mergedIntoExisting"),
        )


@dataclass(frozen=True, slots=True)
class SortedItems:
    """A list's items grouped by a store's departments."""

    departments: list[list[Item]]
    """The items of each department, with the departments in the order the user walks."""
    unplaced_items: list[Item]
    """The items that the API cannot place in a department."""

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> SortedItems:
        return cls(
            departments=[
                get_objects(department, "items", Item.from_dict)
                for department in get_list(data, "departments", as_mapping)
            ],
            unplaced_items=get_objects(data, "unplacedItems", Item.from_dict),
        )


@dataclass(frozen=True, slots=True)
class Store:
    """A store the user has shopped in or marked as a favorite."""

    id: str
    name: str
    address: str | None
    city: str | None
    latitude: float | None
    longitude: float | None
    is_favorite: bool
    last_visited_at: datetime | None
    """When the user last shopped there with the app."""

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Store:
        return cls(
            id=get_str(data, "id"),
            name=get_str(data, "name"),
            address=get_opt_str(data, "address"),
            city=get_opt_str(data, "city"),
            latitude=get_opt_float(data, "latitude"),
            longitude=get_opt_float(data, "longitude"),
            is_favorite=get_bool(data, "isFavorite"),
            last_visited_at=get_opt_time(data, "lastVisitedAt"),
        )


@dataclass(frozen=True, slots=True)
class RecipeSummary:
    """A recipe in the user's recipe box, without its ingredients and instructions."""

    id: str
    """The recipe's id in the user's recipe box."""
    title: str
    tags: list[str]
    """The user's tags, in alphabetical order."""
    grade: int | None
    """The user's grade, from 1 to 5."""
    cooking_time: int | None
    """The minutes it takes."""
    cook_count: int | None
    """How many times the user has cooked it, or None when the request did not ask for it."""
    last_cooked_at: datetime | None
    """When the user last cooked it.

    It is None when the user never cooked it, or when the request did not ask for it.
    """

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> RecipeSummary:
        return cls(**_summary_fields(data))


@dataclass(frozen=True, slots=True)
class Recipe:
    """A recipe in the user's recipe box, with the user's own changes."""

    id: str
    title: str
    tags: list[str]
    grade: int | None
    cooking_time: int | None
    cook_count: int | None
    """How many times the user has cooked it, or None when the request did not ask for it."""
    last_cooked_at: datetime | None
    """When the user last cooked it.

    It is None when the user never cooked it, or when the request did not ask for it.
    """
    description: str | None
    portions: int | None
    """How many portions the recipe's own ingredients are for."""
    selected_portions: str | None
    """The portions the user selected in the app, which `ingredients` is scaled to.

    It is text, because it can be a fraction such as `5/2`.
    """
    portion_type: str | None
    """What a portion is."""
    ingredients: list[str]
    """One line per ingredient. A line can also head a group of ingredients."""
    instructions: str | None
    advice: str | None
    notes: str | None
    """The user's own notes."""
    url: str | None
    """The web page the recipe came from."""

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Recipe:
        return cls(
            **_summary_fields(data),
            description=get_opt_str(data, "description"),
            portions=get_opt_int(data, "portions"),
            selected_portions=get_opt_str(data, "selectedPortions"),
            portion_type=get_opt_str(data, "portionType"),
            ingredients=get_list(data, "ingredients", as_str),
            instructions=get_opt_str(data, "instructions"),
            advice=get_opt_str(data, "advice"),
            notes=get_opt_str(data, "notes"),
            url=get_opt_str(data, "url"),
        )


@dataclass(frozen=True, slots=True)
class RecipeSearchResult:
    """One page of a recipe box search."""

    recipes: list[RecipeSummary]
    total_count: int
    """How many recipes matched in all, on every page."""

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> RecipeSearchResult:
        return cls(
            recipes=get_objects(data, "recipes", RecipeSummary.from_dict),
            total_count=get_int(data, "totalCount"),
        )


@dataclass(frozen=True, slots=True)
class ImportedRecipe:
    """The answer of `import_recipe`."""

    recipe: RecipeSummary
    created: bool
    """True when the recipe is new, and False when the recipe box already held it."""


@dataclass(frozen=True, slots=True)
class Ingredient:
    """An ingredient of a recipe, compared with a shopping list."""

    text: str
    probably_needed: bool
    """False when most people have the item at home, or the list already has it.

    The list counts as having it only when the ingredient has no amount and the list has an
    unchecked item with exactly the same text.
    """

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Ingredient:
        return cls(text=get_str(data, "text"), probably_needed=get_bool(data, "probablyNeeded"))


@dataclass(frozen=True, slots=True)
class Meal:
    """A meal in the active meal plan."""

    id: str
    type: str
    """`recipe` or `title`, as in `MealType`. A later release may add other types."""
    recipe_id: str | None
    """The recipe's id in the recipe box. None for a `title` meal."""
    title: str
    portions: str | None
    """The planned portions, such as `4` or `5/2`."""
    occasion: str | None
    """When the user plans to cook it, in their own words, such as `fredag`."""
    is_purchased: bool
    is_cooked: bool
    ingredients: list[str] | None
    """The ingredients for the planned portions, or None when the request did not ask for them."""

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Meal:
        return cls(
            id=get_str(data, "id"),
            type=get_str(data, "type"),
            recipe_id=get_opt_str(data, "recipeId"),
            title=get_str(data, "title"),
            portions=get_opt_str(data, "portions"),
            occasion=get_opt_str(data, "occasion"),
            is_purchased=get_bool(data, "isPurchased"),
            is_cooked=get_bool(data, "isCooked"),
            ingredients=get_list(data, "ingredients", as_str) if "ingredients" in data else None,
        )


@dataclass(frozen=True, slots=True)
class NewMeal:
    """A meal for `add_meals` to put in the active meal plan."""

    recipe_id: str
    ingredients: list[str]
    """The texts to add to the list.

    Take them from the `text` of the entries that `get_recipe_ingredients` returns. An empty list
    adds nothing and marks the meal as bought.
    """
    occasion: str | None = None
    """When the user plans to cook it, at most 50 characters."""
    portions: str | None = None
    """A whole number such as `2`, or a fraction such as `3/2`.

    Leave it out for the portions the user selected, or else the recipe's own.
    """
    list_id: str | None = None
    """The list to add the ingredients to. Leave it out for the default list."""

    def to_dict(self) -> dict[str, Any]:
        body: dict[str, Any] = {
            "type": MealType.RECIPE.value,
            "recipeId": check_id("recipe_id", self.recipe_id),
            "ingredients": check_strings("ingredients", self.ingredients),
        }
        if self.occasion is not None:
            body["occasion"] = self.occasion
        if self.portions is not None:
            body["portions"] = self.portions
        if self.list_id is not None:
            body["listId"] = check_id("list_id", self.list_id)
        return body


def _summary_fields(data: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": get_str(data, "id"),
        "title": get_str(data, "title"),
        "tags": get_list(data, "tags", as_str),
        "grade": get_opt_int(data, "grade"),
        "cooking_time": get_opt_int(data, "cookingTime"),
        "cook_count": get_opt_int(data, "cookCount"),
        "last_cooked_at": get_opt_time(data, "lastCookedAt"),
    }
